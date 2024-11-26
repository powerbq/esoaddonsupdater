#!/usr/bin/python3

import configparser
import json
import os
import re
import shutil
import sys
import time
import zipfile

from func import download, md5
from rsync import sync


class AddOn:
    def __init__(self):
        self.name = None
        self.version = None
        self.path = None


class SortedDict(dict):

    def items(self):
        return sorted(super().items(), key=key)


def key(item):
    return item[1] if item[0].isnumeric() and type(item[1]) is str else item[0]


def log(status, kind, uid, message):
    print('\t%s\t%s\t%s\t%s' % (status, kind, uid, message))


def dependencies(path):
    z = zipfile.ZipFile(path)

    for name in z.namelist():
        info = z.getinfo(name)

        if info.is_dir() or not name.endswith('.txt'):
            continue

        with z.open(name) as f:
            lines = f.readlines()

        for line in lines:
            text = line.decode('utf-8', errors='ignore')
            if text.startswith('## DependsOn:'):
                for directory in re.sub(r'[=<>][^ ]+', '', text).strip().split()[2:]:
                    if directory in satisfied:
                        continue

                    if any(path.endswith(directory + '/' + directory + '.txt') for path in z.namelist()):
                        satisfied.add(directory)

                        continue

                    if directory in candidates:
                        satisfied.add(directory)

                        if len(candidates[directory]) < 2:
                            process(candidates[directory][0])

                        else:
                            if directory not in c['SelectedLibraries'] or c['SelectedLibraries'][
                                directory] not in candidates:
                                c['SelectedLibraries'][directory] = candidates[directory][0]

                            process(c['SelectedLibraries'][directory])

                        continue

                    else:
                        log('err', 'lib', '-', 'No candidates found for %s' % directory)


def process(uid):
    name = database[uid].name
    version = database[uid].version

    identifier = re.sub(r'\W', '', name) + '_' + uid
    path = 'addons/' + identifier + '.zip'

    invalid = not os.path.exists(path) or not c.has_section(uid) or c[uid].get('UIVersion') != version or c[uid].get(
        'UIMD5') != md5(path)
    if invalid:
        obj_list = json.loads(download(api_url_prefix + '/filedetails/' + uid + '.json'))
        obj = obj_list[0]

        if not c.has_section(uid):
            c.add_section(uid)

        c[uid]['UIVersion'] = obj['UIVersion']
        c[uid]['UIMD5'] = obj['UIMD5']

        body = download(obj['UIDownload'])
        with open(path, 'wb') as f:
            f.write(body)

    status = 'upd' if invalid else '-'
    kind = 'lib' if uid not in addons else '-'
    log(status, kind, uid, name)

    sources.add(path)

    dependencies(path)


def ttc():
    if '1245' not in addons:
        return []

    addon_directory = 'TamrielTradeCentre'
    path = 'ttc/PriceTable.zip'

    os.makedirs(target_directory + '/' + addon_directory, exist_ok=True)

    local_version = None
    if os.path.exists(path):
        z = zipfile.ZipFile(path)
        for name in z.namelist():
            if name.startswith('PriceTable') and name.endswith('.lua'):
                with z.open(name) as f:
                    line = f.readline().decode('utf-8')
                    if line.startswith('--Version = '):
                        local_version = int(line.split('=')[-1].strip())

    obj = json.loads(download(ttc_url_prefix + '/api/GetTradeClientVersion'))
    remote_version = obj['PriceTableVersion']

    if local_version != remote_version:
        price_table = download(ttc_url_prefix + '/Download/PriceTable')
        with open(path, 'wb') as f:
            f.write(price_table)

            print('Successfully updated')
    else:
        print('Already up to date')

    sync([path], target_directory + '/' + addon_directory, clean=False)

    result = []
    z = zipfile.ZipFile(path)
    for name in z.namelist():
        result.append('^' + addon_directory + '/' + name.replace('.', r'\.'))

    return result


def run():
    obj_list = json.loads(download(api_url_prefix + '/filelist.json'))
    for obj in obj_list:
        uid = obj['UID']
        name = obj['UIName']
        version = obj['UIVersion']

        database[uid] = AddOn()
        database[uid].name = name
        database[uid].version = version

        for directory in obj['UIDir']:
            if directory not in candidates:
                candidates[directory] = []

            candidates[directory].append(uid)

    for uid in addons.keys():
        if uid in database:
            if not c.has_section(uid):
                c.add_section(uid)

            addons[uid] = database[uid].name

            process(uid)

        else:
            name = addons[uid]
            if name:
                log('err', '-', uid, '%s (Not found in database)' % name)

            else:
                log('err', '-', uid, 'Not found in database')

    for path in sorted(os.listdir('custom')):
        if path.endswith('.zip'):
            path = 'custom/' + path
            if os.path.isfile(path):
                name = path.removeprefix('custom/').removesuffix('.zip')
                log('err', '-', '-', 'Custom (%s)' % name)

                sources.add(path)

                dependencies(path)

    sync(sources, target_directory, exclude_patterns=ttc())


def delete(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def cleanup():
    for path in os.listdir('addons'):
        if 'addons' + '/' + path not in sources:
            delete('addons' + '/' + path)

    for path in os.listdir('custom'):
        if not path.endswith('.zip'):
            delete('custom' + '/' + path)

    for path in os.listdir('ttc'):
        if path != 'PriceTable.zip':
            delete('ttc' + '/' + path)

    for section in c.sections():
        if section == 'General':
            for option in c[section].keys():
                if option not in {'TargetDirectory'}:
                    c.remove_option(section, option)
        elif section == 'URLPrefixes':
            for option in c[section].keys():
                if option not in {'API', 'TTC'}:
                    c.remove_option(section, option)

        elif section == 'AddOns':
            for option in c[section].keys():
                if not option.isnumeric():
                    c.remove_option(section, option)

        elif section == 'SelectedLibraries':
            for option in c[section].keys():
                value = c[section][option]
                if value not in database or len(candidates[option]) < 2:
                    c.remove_option(section, option)

        else:
            if section not in database:
                c.remove_section(section)

            else:
                for option in c[section].keys():
                    if option not in {'UIVersion', 'UIMD5'}:
                        c.remove_option(section, option)


def save():
    with open('app.ini', 'w') as f:
        c.write(f)


if __name__ == '__main__':
    start_time = time.time()
    file_path = os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)
    file_directory = os.path.dirname(os.path.abspath(file_path))

    os.chdir(file_directory)

    c = configparser.ConfigParser(dict_type=SortedDict)
    c.optionxform = str
    c.add_section('General')
    c.add_section('URLPrefixes')
    c.add_section('AddOns')
    c.add_section('SelectedLibraries')
    c['General']['TargetDirectory'] = 'target/AddOns'
    c['URLPrefixes']['API'] = 'https://api.mmoui.com/v3/game/ESO'
    c['URLPrefixes']['TTC'] = 'https://eu.tamrieltradecentre.com'

    if os.path.exists('app.ini'):
        c.read('app.ini')

    target_directory = c['General']['TargetDirectory']
    api_url_prefix = c['URLPrefixes']['API']
    ttc_url_prefix = c['URLPrefixes']['TTC']

    os.makedirs(target_directory, exist_ok=True)

    os.makedirs('addons', exist_ok=True)
    os.makedirs('custom', exist_ok=True)
    os.makedirs('ttc', exist_ok=True)

    addons = c['AddOns']

    database = {}
    candidates = {}

    satisfied = set()
    sources = set()

    run()
    cleanup()
    save()

    print(' * Done (%s) - %.2fs' % (__file__, time.time() - start_time))

    print()
    print('Press Enter to exit')
    input()

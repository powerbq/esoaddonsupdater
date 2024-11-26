#!/usr/bin/python3

import concurrent.futures
import datetime
import math
import os
import re
import shutil
import subprocess
import time
import zipfile
import zlib


class Info:
    def __init__(self):
        self.source = None
        self.is_zip_file = False
        self.size = None
        self.crc32 = None
        self.modified = None


class Sync:
    def __init__(self):
        self.sources = None
        self.destination = None
        self.clean = True
        self.compare = True
        self.checksums = False
        self.check_time = True
        self.restore_time = True
        self.force_restore = False
        self.reflink = False
        self.dry_run = False
        self.verbose = True
        self.include_patterns = []
        self.exclude_patterns = []
        self.threads = os.cpu_count()
        self.block_size = 512 * 1024

        self.__skip_cache = set()
        self.__compiled_include_patterns = []
        self.__compiled_exclude_patterns = []

    def perform(self):
        self.__skip_cache.clear()

        for pattern in self.include_patterns:
            self.__compiled_include_patterns.append(re.compile(pattern))

        for pattern in self.exclude_patterns:
            self.__compiled_exclude_patterns.append(re.compile(pattern))

        if not self.dry_run:
            os.makedirs(self.destination, exist_ok=True)

        l_list = {}
        r_list = self.__tree(self.destination)

        if type(self.sources) is str:
            self.sources = [self.sources]

        for source in self.sources:
            if not os.path.exists(source):
                print(source, 'not found')
                return

            l_list |= self.__tree(source)

        excess = r_list.keys() - l_list.keys()
        updated = l_list.keys() - r_list.keys()
        exists = l_list.keys() - updated

        if not self.force_restore:
            comparable = []

            for path in exists:
                result = None

                l_info = l_list[path]
                r_info = r_list[path]

                if not path.endswith('/'):
                    if l_info.size == r_info.size:
                        if not self.check_time or l_info.modified == r_info.modified:
                            if self.compare:
                                comparable.append((path, l_info,))

                        else:
                            l_modified = datetime.datetime.fromtimestamp(l_info.modified)
                            r_modified = datetime.datetime.fromtimestamp(r_info.modified)

                            result = 'modified time:', path, l_modified, '!=', r_modified

                    else:
                        result = 'size:', path, l_info.size, '!=', r_info.size

                if result:
                    updated.add(path)

                    if self.verbose:
                        print(*result)

            comparable = sorted(comparable, key=lambda x: x[1].size, reverse=True)

            if self.threads > 1:
                chunk_size = math.ceil(len(comparable) / self.threads) or 1
                chunk_cnt = math.ceil(len(comparable) / chunk_size)
                chunks = [comparable[i::chunk_cnt] for i in range(chunk_cnt)]

                with concurrent.futures.ThreadPoolExecutor(self.threads) as executor:
                    futures = [executor.submit(self.__compare, chunk) for chunk in chunks]
                    for future in futures:
                        updated.update(future.result())

            else:
                updated.update(self.__compare(comparable))

        else:
            updated = updated.union(exists)

        if self.clean:
            for path in sorted(excess, reverse=True):
                if self.__skip(path):
                    continue

                if not self.dry_run:
                    if not path.endswith('/'):
                        os.remove(self.destination + '/' + path)

                    else:
                        os.rmdir(self.destination + '/' + path)

                if self.verbose:
                    print('deleted:', path)

        zip_files = {}

        reflink_path = os.path.dirname(__file__) + '/reflink.exe'

        for path in sorted(updated):
            if path.endswith('/'):
                if path not in exists:
                    if not self.dry_run:
                        os.makedirs(self.destination + '/' + path)

                    print('created:', path)

            else:
                if not self.dry_run:
                    l_info = l_list[path]

                    if os.path.exists(self.destination + '/' + path):
                        os.remove(self.destination + '/' + path)

                    if l_info.is_zip_file:
                        if l_info.source not in zip_files:
                            zip_files[l_info.source] = zipfile.ZipFile(l_info.source)

                        zip_file = zip_files[l_info.source]

                        f1 = zip_file.open(path)
                        f2 = open(self.destination + '/' + path, 'wb')

                        while data := f1.read(self.block_size):
                            f2.write(data)

                        f1.close()
                        f2.close()
                    else:
                        if not self.reflink:
                            shutil.copyfile(l_info.source + '/' + path, self.destination + '/' + path)

                        else:
                            subprocess.call([reflink_path, l_info.source + '/' + path, self.destination + '/' + path])

                if self.verbose:
                    if path in exists:
                        print('updated:', path)

                    else:
                        print('created:', path)

        if not self.dry_run and self.restore_time:
            r_list = self.__tree(self.destination)

            for path in r_list.keys():
                if not path.endswith('/') and path in l_list:
                    l_info = l_list[path]
                    r_info = r_list[path]

                    if l_info.modified != r_info.modified:
                        os.utime(self.destination + '/' + path, (l_info.modified, l_info.modified))

                        if self.verbose:
                            print('restored modified time:', path)

    def __compare(self, comparable):
        updated = set()

        zip_files = {}

        for pair in comparable:
            path, info = pair

            result = None

            if info.is_zip_file:
                if info.source not in zip_files:
                    zip_files[info.source] = zipfile.ZipFile(info.source)

                zip_file = zip_files[info.source]

                f1 = None
                if not self.checksums:
                    f1 = zip_file.open(path)

            else:
                f1 = open(info.source + '/' + path, 'rb')

            f2 = open(self.destination + '/' + path, 'rb')

            crc32 = 0
            while r_data := f2.read(self.block_size):
                if info.is_zip_file and self.checksums:
                    crc32 = zlib.crc32(r_data, crc32)

                else:
                    l_data = f1.read(self.block_size)
                    if l_data != r_data:
                        result = 'mismatch:', path
                        break

            if self.checksums and info.crc32 is not None and info.crc32 != crc32:
                result = 'crc32:', path, info.crc32, '!=', crc32

            if f1 is not None:
                f1.close()

            f2.close()

            if result:
                updated.add(path)

                if self.verbose:
                    print(*result)

        return updated

    def __tree(self, source):
        if source == '':
            return {}

        if not os.path.exists(source):
            return {}

        cut = len(source) + 1

        result = {}

        if os.path.isfile(source):
            if zipfile.is_zipfile(source):
                z = zipfile.ZipFile(source)

                for name in sorted(z.namelist()):
                    i = z.getinfo(name)

                    info = Info()

                    path = i.filename.rstrip('/')
                    if i.is_dir():
                        path += '/'

                        if self.__skip(path):
                            continue

                    else:
                        if self.__skip(path):
                            continue

                        modified_str = '%d-%02d-%02d %02d:%02d:%02d' % i.date_time
                        modified_datetime = datetime.datetime.strptime(modified_str, '%Y-%m-%d %H:%M:%S')
                        modified_timestamp = time.mktime(modified_datetime.timetuple())

                        info.source = source
                        info.is_zip_file = True
                        info.modified = int(modified_timestamp)
                        info.size = i.file_size
                        info.crc32 = i.CRC

                    result[path] = info

            else:
                path = os.path.basename(source)

                if self.__skip(path):
                    return result

                info = Info()
                info.source = os.path.dirname(source)
                info.modified = int(os.path.getmtime(source))
                info.size = os.path.getsize(source)

                result[path] = info

        else:
            for dir_path, dir_names, file_names in os.walk(source):
                dir_path = dir_path.replace(os.sep, '/')
                short_path = dir_path[cut:]
                if short_path:
                    short_path += '/'

                for dir_name in sorted(dir_names):
                    path = short_path + dir_name + '/'

                    if self.__skip(path):
                        continue

                    info = Info()

                    result[path] = info

                for file_name in sorted(file_names):
                    path = short_path + file_name

                    if self.__skip(path):
                        continue

                    info = Info()
                    info.source = source
                    info.modified = int(os.path.getmtime(dir_path + '/' + file_name))
                    info.size = os.path.getsize(dir_path + '/' + file_name)

                    result[path] = info

        for path in sorted(result.keys()):
            while True:
                path = os.path.dirname(path.rstrip('/')) + '/'

                if path == '/':
                    break

                if path not in result:
                    info = Info()

                    result[path] = info

        return result

    def __skip(self, path):
        if path in self.__skip_cache:
            return True

        result = True

        for compiled_pattern in self.__compiled_include_patterns:
            if compiled_pattern.findall(path):
                result = False
                break

        if result:
            result = False

            for compiled_pattern in self.__compiled_exclude_patterns:
                if compiled_pattern.findall(path):
                    result = True
                    break

        if result:
            self.__skip_cache.add(path)

        return result


def sync(sources, destination, **kwargs):
    task = Sync()

    task.sources = sources
    task.destination = destination

    for key in kwargs:
        getattr(task, key.lstrip('_'))
        setattr(task, key.lstrip('_'), kwargs[key])

    task.perform()

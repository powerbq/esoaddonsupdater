#!/usr/bin/python3

import hashlib

import requests

block_size = 512 * 1024


def download(url):
    response = requests.get(url)
    response.raise_for_status()

    return response.content


def md5(path):
    hash_object = hashlib.md5()

    with open(path, 'rb') as f:
        while data := f.read(block_size):
            hash_object.update(data)

    return hash_object.hexdigest()

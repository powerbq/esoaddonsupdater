#!/bin/bash

cd $(dirname $0)

cd build

pyinstaller --clean --onefile --specpath .. --console ../app.py

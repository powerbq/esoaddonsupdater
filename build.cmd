@echo off

cd build

pyinstaller --clean --onefile --specpath .. --console ..\app.py

pause

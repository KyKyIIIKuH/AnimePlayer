@echo off
setlocal

:: \u041f\u043e\u043b\u0443\u0447\u0430\u0435\u043c \u043f\u0443\u0442\u044c \u0434\u043e \u0441\u043a\u0440\u0438\u043f\u0442\u0430
set SCRIPT_DIR=%~dp0

set LC_ALL=C
set LC_NUMERIC=C
set QT_QPA_PLATFORM=windows

set PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe
set MAIN=%SCRIPT_DIR%main.py
set LOG=%SCRIPT_DIR%log.txt

%PYTHON% -u %MAIN% %* > "%LOG%" 2>&1

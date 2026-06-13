@echo off
setlocal enabledelayedexpansion

REM ==========================================
REM ОТКЛЮЧЕНИЕ ОСТАНОВКИ ПРИ ОШИБКАХ НЕПРЯМОЕ
REM ==========================================

REM Получаем путь до текущего скрипта
set "PATH_SCRIPT=%~dp0"

REM Установка зависимостей
python -m pip install -r "%PATH_SCRIPT%requirements.txt"
if errorlevel 1 goto error

REM ==========================================
REM НАСТРОЙКИ
REM ==========================================
set "APP_NAME=AnimePlayer.exe"
set "ENTRY_POINT=main.py"

set "BUILD_DIR=nuitka_build"
set "RELEASE_DIR=release"

REM ==========================================
REM 1. ОЧИСТКА СТАРЫХ СБОРОК
REM ==========================================
echo [1/4] Очистка старых папок...

if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"

REM ==========================================
REM 4. КОМПИЛЯЦИЯ ЧЕРЕЗ NUITKA
REM ==========================================
echo [4/4] Компиляция через Nuitka...

python -m nuitka ^
    --standalone ^
    --onefile ^
    --output-dir="%BUILD_DIR%" ^
    --output-filename="%APP_NAME%" ^
    --enable-plugin=pyqt6 ^
    --include-package=app ^
    --jobs=12 ^
    "%PATH_SCRIPT%%ENTRY_POINT%"

if errorlevel 1 goto error

REM ==========================================
REM 5. ФИНАЛИЗАЦИЯ
REM ==========================================
echo Сборка завершена успешно!

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
copy "%BUILD_DIR%\%APP_NAME%" "%RELEASE_DIR%\%APP_NAME%" >nul

exit /b 0

:error
echo.
echo [ERROR] Сборка провалена!
exit /b 1

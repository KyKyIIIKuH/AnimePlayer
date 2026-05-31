#!/bin/bash

# Получаем путь до текущего скрипта
path="$(dirname "$(realpath "$0")")"
 
LC_ALL=C LC_NUMERIC=C QT_QPA_PLATFORM=xcb \
$path/venv/bin/python -u "$path/main.py" "$@" 2>&1 | tee "$path/log.txt"

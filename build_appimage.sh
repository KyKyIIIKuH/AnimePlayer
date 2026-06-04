#!/bin/bash

# Получаем путь до текущего скрипта
path="$(dirname "$(realpath "$0")")"

# Получаем полный путь к выбранному файлу
selected_path="$path/python3.13.7-cp313-cp313-manylinux_2_28_x86_64.appimage"

# Проверяем, существует ли папка build
if [ -d "$path/build" ]; then
    echo "Папка build уже существует. Удаляю..."
    rm -rf "$path/build"
fi

mkdir -p "$path/build"

# Переходим в папку build
cd $path/build

# Извлеките его содержимое в папку 'squashfs-root'
"$selected_path" --appimage-extract

cd $path/build/squashfs-root

# Установите ваши библиотеки
echo "Установка зависимостей из requirements.txt..."
./usr/bin/python3.13 -m pip install -r "$path/requirements.txt"

# Удалите старый метафайл или обновите его
rm ./usr/share/metainfo/python3.13.7.appdata.xml

# Создайте новый для вашего приложения
cat > ./usr/share/metainfo/animeplayer.appdata.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>com.yourcompany.animeplayer</id>
  <name>AnimePlayer</name>
  <summary>Python-based Anime Player</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <description>
    <p>A simple anime player built with Python</p>
  </description>
</component>
EOF

# Если нет, создайте его:
cat > ./AppRun << 'EOF'
#!/bin/bash

HERE="$(dirname "$(readlink -f "$0")")"

if [ -n "${APPIMAGE}" ]; then
    HERE="${APPDIR}"
fi

# Находим Python
PYTHON_BIN="${HERE}/opt/python3.13/bin/python3.13"

# Определяем правильный PYTHONHOME на основе расположения Python
PYTHON_BIN_DIR="$(dirname "${PYTHON_BIN}")"
PYTHON_HOME="$(dirname "${PYTHON_BIN_DIR}")"

export PYTHONHOME="${PYTHON_HOME}"
export PYTHONPATH="${PYTHON_HOME}/lib/python3.13:${PYTHON_HOME}/lib/python3.13/lib-dynload:${HERE}/usr/src"

# Проверяем существование encodings модуля
if [ ! -f "${PYTHON_HOME}/lib/python3.13/encodings/__init__.py" ]; then
    echo "Error: encodings module not found at ${PYTHON_HOME}/lib/python3.13/encodings/"
    echo "Trying alternative path..."

    # Альтернативный путь
    export PYTHONHOME="${HERE}/usr"
    export PYTHONPATH="${HERE}/usr/lib/python3.13:${HERE}/usr/lib/python3.13/lib-dynload:${HERE}/usr/src"
fi

export SSL_CERT_FILE="${HERE}/opt/_internal/certs.pem"
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONIOENCODING=utf-8
export QT_QPA_PLATFORM=xcb

exec "${PYTHON_BIN}" -u "${HERE}/usr/src/main.py" "$@"
EOF

# Скопируйте файлы вашего приложения, например, в папку /usr/src
mkdir -p ./usr/src

cp "$path/main.py" ./usr/src/
cp "$path/requirements.txt" ./usr/src/
cp "$path/oauth_manager.py" ./usr/src/
cp "$path/oauth_server.py" ./usr/src/
cp "$path/icon.png" ./python.png

cd $path

$path/appimagetool-x86_64.AppImage $path/build/squashfs-root $path/build/AnimePlayer-x86_64.AppImage

echo "Success"

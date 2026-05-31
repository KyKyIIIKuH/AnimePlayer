#!/bin/bash

# Получаем путь до текущего скрипта
path="$(dirname "$(realpath "$0")")"

# Папка с AppImage файлами (путь на уровень выше)
appimage_dir="$(realpath "$path/../PythonAppImage")"

# Получаем список AppImage файлов вручную и извлекаем только имена файлов для отображения
mapfile -t appimages < <(find "$appimage_dir" -maxdepth 1 -type f -iname "*.AppImage")

# Проверяем, есть ли файлы в папке
if [ ${#appimages[@]} -eq 0 ]; then
    echo "Нет файлов AppImage в папке $appimage_dir."
    exit 1
fi

# Выводим список файлов для выбора (только имена файлов)
echo "Выберите файл AppImage:"
select appimage_file in "${appimages[@]}"; do
    if [ -n "$appimage_file" ]; then
        chmod +x $appimage_file
        # Извлекаем только имя файла
        selected_file=$(basename "$appimage_file")
        echo "Вы выбрали: $selected_file"
        break
    else
        echo "Неверный выбор. Пожалуйста, выберите номер из списка."
    fi
done

# Получаем полный путь к выбранному файлу
selected_path="$appimage_dir/$selected_file"

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
./usr/bin/python3.11 -m pip install -r "$path/requirements.txt"

# Удалите старый метафайл или обновите его
rm ./usr/share/metainfo/python3.11.8.appdata.xml

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
PYTHON_BIN="${HERE}/opt/python3.11/bin/python3.11"

# Определяем правильный PYTHONHOME на основе расположения Python
PYTHON_BIN_DIR="$(dirname "${PYTHON_BIN}")"
PYTHON_HOME="$(dirname "${PYTHON_BIN_DIR}")"

export PYTHONHOME="${PYTHON_HOME}"
export PYTHONPATH="${PYTHON_HOME}/lib/python3.11:${PYTHON_HOME}/lib/python3.11/lib-dynload:${HERE}/usr/src"

# Проверяем существование encodings модуля
if [ ! -f "${PYTHON_HOME}/lib/python3.11/encodings/__init__.py" ]; then
    echo "Error: encodings module not found at ${PYTHON_HOME}/lib/python3.11/encodings/"
    echo "Trying alternative path..."

    # Альтернативный путь
    export PYTHONHOME="${HERE}/usr"
    export PYTHONPATH="${HERE}/usr/lib/python3.11:${HERE}/usr/lib/python3.11/lib-dynload:${HERE}/usr/src"
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

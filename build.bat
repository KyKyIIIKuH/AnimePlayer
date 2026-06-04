 .\venv\Scripts\python.exe -m nuitka ^
  --standalone ^
  --enable-plugin=pyqt6 ^
  --prefer-source-code ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=logo.ico ^
  main.py

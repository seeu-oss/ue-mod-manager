@echo off
cd /d "%~dp0"
echo 安装打包工具...
python -m pip install pyinstaller --quiet
echo 开始打包...
python -m PyInstaller --onefile --noconsole --name UEMM --icon docs\icon.ico --workpath build --distpath dist --specpath . launcher.py
echo.
echo 完成，产物在 dist\UEMM.exe
pause

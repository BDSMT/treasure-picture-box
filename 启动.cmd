@echo off
chcp 936 >nul
rem 源码运行用。发布版直接双击 藏图盒.exe，不需要这个文件。
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if errorlevel 1 goto nopy
start "" pythonw.exe "%~dp0藏图盒.py"
exit /b 0
:nopy
echo 没找到 pythonw.exe。
echo 请安装 Python 3.10 以上版本，安装时勾选 Add Python to PATH。
echo 或者在本目录执行: python 藏图盒.py
pause

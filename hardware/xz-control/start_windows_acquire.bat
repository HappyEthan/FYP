@echo off
setlocal
cd /d "%~dp0"
python "%~dp0windows_acquire.py" %*
if errorlevel 1 (
    echo.
    echo 采集脚本未完成，请查看上面的错误信息。
)
echo.
pause

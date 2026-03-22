@echo off
setlocal

set "PROJECT_DIR=%~dp0spotify-downloader-master"

if not exist "%PROJECT_DIR%\web-status.bat" (
    echo Could not find the status script in:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

call "%PROJECT_DIR%\web-status.bat" %*
exit /b %errorlevel%

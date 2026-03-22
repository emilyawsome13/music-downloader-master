@echo off
setlocal

set "PROJECT_DIR=%~dp0spotify-downloader-master"

if not exist "%PROJECT_DIR%\run-web.bat" (
    echo Could not find the web launcher in:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

call "%PROJECT_DIR%\run-web.bat" %*
exit /b %errorlevel%

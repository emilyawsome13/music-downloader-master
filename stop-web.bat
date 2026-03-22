@echo off
setlocal

set "PROJECT_DIR=%~dp0spotify-downloader-master"

if not exist "%PROJECT_DIR%\stop-web.bat" (
    echo Could not find the stop script in:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

call "%PROJECT_DIR%\stop-web.bat" %*
exit /b %errorlevel%

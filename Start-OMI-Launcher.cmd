@echo off
setlocal

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%scripts\start-omi-launcher-hidden.vbs"

echo %ROOT% | findstr /i "\\AppData\\Local\\Temp\\.*\.zip\." >nul
if not errorlevel 1 (
  echo This launcher is running from a temporary ZIP preview folder.
  echo Please right click the downloaded ZIP file, choose Extract All, then run Start-OMI-Launcher.cmd from the extracted folder.
  echo.
  echo Current path: %ROOT%
  pause
  exit /b 1
)

if not exist "%SCRIPT%" (
  echo Missing launcher script: %SCRIPT%
  echo.
  echo Make sure you extracted the whole ZIP file before running Start-OMI-Launcher.cmd.
  pause
  exit /b 1
)

"%SystemRoot%\System32\wscript.exe" "%SCRIPT%"

endlocal
exit /b 0

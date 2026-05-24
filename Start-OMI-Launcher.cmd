@echo off
setlocal

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%scripts\omi-launcher.ps1"

if not exist "%SCRIPT%" (
  echo Missing launcher script: %SCRIPT%
  pause
  exit /b 1
)

start "Open Market Intelligence Launcher" powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%SCRIPT%"

endlocal

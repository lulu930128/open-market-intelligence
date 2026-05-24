@echo off
setlocal

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%scripts\start-omi-launcher-hidden.vbs"

if not exist "%SCRIPT%" (
  echo Missing launcher script: %SCRIPT%
  pause
  exit /b 1
)

"%SystemRoot%\System32\wscript.exe" "%SCRIPT%"

endlocal
exit /b 0

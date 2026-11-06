@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0internos\instalar.ps1"
if errorlevel 1 (
  echo No se pudo completar la instalacion. Consulta README.md.
  pause
  exit /b 1
)
echo Instalacion lista. Abri "Abrir herramienta.cmd".
pause

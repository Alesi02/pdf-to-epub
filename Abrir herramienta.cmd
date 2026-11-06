@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0internos\iniciar.ps1"
if errorlevel 1 (
  echo No se pudo iniciar. Consultar LEEME.md para instalar las dependencias.
  pause
)

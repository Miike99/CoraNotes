@echo off
REM Doble clic para detener CoraNotes (cierra tambien a Cora)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\detener.ps1"
pause

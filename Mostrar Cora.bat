@echo off
REM Muestra a Cora, la mascota de escritorio (CoraNotes debe estar iniciado)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\mascota.ps1"
pause

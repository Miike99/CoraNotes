@echo off
REM Reinicia la demostracion desde cero (borra solo los datos ficticios de la demo)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\reiniciar_demo.ps1"
pause

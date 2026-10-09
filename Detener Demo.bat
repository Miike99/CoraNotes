@echo off
REM Detiene la demostracion
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\detener.ps1" -Demo
pause

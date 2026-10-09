# Ejecuta las pruebas automáticas (reloj, notificaciones y Gemini simulados: no consumen API).
. (Join-Path $PSScriptRoot '_comun.ps1')
$py = Preparar-Entorno
if (-not $py) { exit 1 }
& $py -m pip install --disable-pip-version-check -q -r (Join-Path $Proyecto 'requirements-dev.txt')
Push-Location $Proyecto
try { & $py -m pytest -q tests; exit $LASTEXITCODE } finally { Pop-Location }

# Restaura una copia de seguridad. La app debe estar detenida.
# Uso: .\scripts\restaurar_copia.ps1 -Archivo "C:\ruta\coranotes-copia-AAAAMMDD-HHMMSS.zip"
param([Parameter(Mandatory = $true)][string]$Archivo, [switch]$Demo)
. (Join-Path $PSScriptRoot '_comun.ps1')

if (Probar-Servidor (Obtener-Puerto -Demo:$Demo)) {
    Write-Host 'Primero detené la app: .\scripts\detener.ps1' -ForegroundColor Red
    exit 1
}
Fijar-Modo -Demo:$Demo -Puerto (Obtener-Puerto -Demo:$Demo)
$py = Preparar-Entorno
if (-not $py) { exit 1 }
Push-Location $Proyecto
try { & $py -m coranotes restaurar $Archivo; exit $LASTEXITCODE } finally { Pop-Location }

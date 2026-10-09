# Muestra a Cora, la mascota de escritorio (la abre si estaba cerrada). CoraNotes debe estar en ejecución.
# Uso: .\scripts\mascota.ps1   |   .\scripts\mascota.ps1 -Demo
param([switch]$Demo)
. (Join-Path $PSScriptRoot '_comun.ps1')

$puerto = Obtener-Puerto -Demo:$Demo
Fijar-Modo -Demo:$Demo -Puerto $puerto
if (-not (Probar-Servidor $puerto)) {
    Write-Host 'CoraNotes no está en ejecución. Inicialo con Iniciar CoraNotes.bat (también abre a Cora).' -ForegroundColor Yellow
    exit 1
}
$pyw = Obtener-Pythonw
if (-not $pyw) { Write-Host 'No se encontró Python. Ejecutá Iniciar CoraNotes.bat.' -ForegroundColor Red; exit 1 }
Iniciar-Oculto $pyw '-m bitacora.mascota' | Out-Null
Write-Host 'Listo: Cora aparece en el escritorio (si ya estaba abierta, se vuelve a mostrar).' -ForegroundColor Green

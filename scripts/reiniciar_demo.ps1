# Reinicia la DEMOSTRACIÓN desde cero: detiene la demo, borra solo sus datos ficticios y la vuelve a iniciar.
# No toca tus datos reales (%LOCALAPPDATA%\CoraNotes) ni el proyecto.
# Uso: .\scripts\reiniciar_demo.ps1
param([switch]$SinNavegador)
. (Join-Path $PSScriptRoot '_comun.ps1')

$datos = Obtener-CarpetaDatos -Demo
$entrada = "$datos-entrada"   # carpeta de entrada que crea «Cargar datos ficticios»

# Protección: solo se borran carpetas de demo reconocibles.
$nombre = Split-Path $datos -Leaf
if ($nombre -notlike '*demo*') {
    Write-Host "La carpeta de datos de demo ($datos) no tiene un nombre de demo; por seguridad no se borra." -ForegroundColor Red
    exit 1
}
$real = Obtener-CarpetaDatos
if ((Test-Path $real) -and (Test-Path $datos) -and ((Resolve-Path $real).Path -eq (Resolve-Path $datos).Path)) {
    Write-Host 'La carpeta de demo coincide con la de datos reales; no se borra nada.' -ForegroundColor Red
    exit 1
}

Write-Host 'Deteniendo la demo...'
& (Join-Path $PSScriptRoot 'detener.ps1') -Demo | Out-Host

foreach ($carpeta in @($datos, $entrada)) {
    if (Test-Path $carpeta) {
        for ($i = 0; $i -lt 10; $i++) {
            try { Remove-Item $carpeta -Recurse -Force -ErrorAction Stop; break }
            catch { Start-Sleep -Milliseconds 500 }   # algún archivo puede seguir en uso un instante
        }
        if (Test-Path $carpeta) {
            Write-Host "No se pudo borrar $carpeta (¿está abierta en otro programa?)." -ForegroundColor Red
            exit 1
        }
        Write-Host "Borrado: $carpeta"
    }
}

Write-Host 'Iniciando la demo limpia...'
& (Join-Path $PSScriptRoot 'iniciar.ps1') -Demo -SinNavegador:$SinNavegador
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Listo. En Inicio presioná «Cargar datos ficticios» justo antes de mostrar (recordatorio a los 2 min, cierre a los 6 min).' -ForegroundColor Green

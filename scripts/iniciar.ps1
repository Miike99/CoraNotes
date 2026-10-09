# Inicia CoraNotes en segundo plano (solo 127.0.0.1) y abre el navegador.
# Uso:  .\scripts\iniciar.ps1            (normal)
#       .\scripts\iniciar.ps1 -SinNavegador
#       .\scripts\iniciar.ps1 -Demo      (datos ficticios, carpeta y puerto separados, sin Gemini)
#       .\scripts\iniciar.ps1 -SinMascota (no abre a Cora, la mascota de escritorio)
param([switch]$SinNavegador, [switch]$Demo, [switch]$SinMascota)
. (Join-Path $PSScriptRoot '_comun.ps1')

$puerto = Obtener-Puerto -Demo:$Demo
$url = "http://127.0.0.1:$puerto/"
Fijar-Modo -Demo:$Demo -Puerto $puerto

function Iniciar-Mascota {
    # Proceso aparte (sin consola). Si Cora ya está abierta, el nuevo proceso solo le pide que se muestre y termina.
    if ($SinMascota) { return }
    $pyw = Obtener-Pythonw
    if ($pyw) { Iniciar-Oculto $pyw '-m bitacora.mascota' | Out-Null }
}

if (Probar-Servidor $puerto) {
    Write-Host "CoraNotes ya está en ejecución en $url"
    Iniciar-Mascota
    if (-not $SinNavegador) { Start-Process $url }
    exit 0
}

$py = Preparar-Entorno
if (-not $py) { exit 1 }

# Un log por puerto: dos instancias (por ejemplo normal y demo) nunca compiten por el mismo archivo.
$log = Join-Path $env:TEMP "coranotes-arranque-$puerto.log"
Write-Host "Iniciando CoraNotes$(if ($Demo) { ' (MODO DEMO)' })..."
$proc = Iniciar-Oculto $env:ComSpec "/s /c `"`"$py`" -m bitacora > `"$log`" 2> `"$log.err`"`""

# El primer inicio después de descomprimir puede tardar (Windows analiza los archivos nuevos).
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Milliseconds 500
    if ($i -eq 20) { Write-Host 'El primer inicio puede tardar hasta un minuto. Esperá, por favor...' }
    if (Probar-Servidor $puerto) {
        Write-Host "Listo: $url  (podés cerrar esta ventana; la app sigue funcionando)" -ForegroundColor Green
        Iniciar-Mascota
        if (-not $SinMascota) { Write-Host 'Cora aparece en el escritorio (abajo a la derecha). Clic derecho: menú.' }
        $sufijo = if ($Demo) { ' -Demo' } else { '' }
        Write-Host "Para detenerla: .\scripts\detener.ps1$sufijo"
        if (-not $SinNavegador) { Start-Process $url }
        exit 0
    }
    if ($proc.HasExited) { break }
}
Write-Host 'La app no respondió. Detalle del arranque:' -ForegroundColor Red
if (Test-Path $log) { Get-Content $log -Tail 20 }
if (Test-Path "$log.err") { Get-Content "$log.err" -Tail 20 }
exit 1

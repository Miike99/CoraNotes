# Detiene CoraNotes de forma ordenada (y, si no responde, finaliza su proceso).
# Uso: .\scripts\detener.ps1   |   .\scripts\detener.ps1 -Demo
param([switch]$Demo)
. (Join-Path $PSScriptRoot '_comun.ps1')

$puerto = Obtener-Puerto -Demo:$Demo
$run = Join-Path (Obtener-CarpetaDatos -Demo:$Demo) 'run'
$tokenArchivo = Join-Path $run 'detener.token'
$pidArchivo = Join-Path $run 'coranotes.pid'

# Cora también se cierra al detener toda la app (pedido ordenado y, si no responde, se finaliza).
$pidMascota = Join-Path $run 'mascota.pid'
if (Test-Path $pidMascota) {
    Set-Content -Path (Join-Path $run 'mascota.salir') -Value 'salir' -Encoding ascii
    $idM = [int](Get-Content $pidMascota -Raw).Trim()
    for ($i = 0; $i -lt 16; $i++) {
        if (-not (Get-Process -Id $idM -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
    $pm = Get-Process -Id $idM -ErrorAction SilentlyContinue
    if ($pm -and $pm.ProcessName -like 'python*') { Stop-Process -Id $idM -Force }
    Remove-Item (Join-Path $run 'mascota.salir') -ErrorAction SilentlyContinue
    Write-Host 'Cora se cerró.'
}

if (-not (Test-Path $tokenArchivo) -and -not (Probar-Servidor $puerto)) {
    Write-Host 'CoraNotes no está en ejecución.'
    exit 0
}
if (Test-Path $tokenArchivo) {
    $token = (Get-Content $tokenArchivo -Raw).Trim()
    try {
        Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$puerto/api/sistema/detener" `
            -Headers @{ 'X-CoraNotes-Detener' = $token } -TimeoutSec 5 | Out-Null
    } catch { }
}
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (-not (Probar-Servidor $puerto)) { Write-Host 'CoraNotes se detuvo.' -ForegroundColor Green; exit 0 }
}
if (Test-Path $pidArchivo) {
    $procId = [int](Get-Content $pidArchivo -Raw).Trim()
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like 'python*') {
        Stop-Process -Id $procId -Force
        Write-Host 'Se finalizó el proceso de CoraNotes.' -ForegroundColor Yellow
        exit 0
    }
}
Write-Host 'No se pudo detener automáticamente. Cerrá el proceso "python" desde el Administrador de tareas.' -ForegroundColor Red
exit 1

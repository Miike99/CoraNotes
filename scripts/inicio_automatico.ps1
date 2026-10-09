# Inicio automático OPCIONAL con Windows: crea o quita un acceso directo en tu carpeta "Inicio".
# No usa tareas programadas ni permisos de administrador.
# Uso: .\scripts\inicio_automatico.ps1 -Activar   |   .\scripts\inicio_automatico.ps1 -Desactivar
param([switch]$Activar, [switch]$Desactivar)
. (Join-Path $PSScriptRoot '_comun.ps1')

$inicio = [Environment]::GetFolderPath('Startup')
$acceso = Join-Path $inicio 'CoraNotes.lnk'
$anterior = Join-Path $inicio 'Bitacora IA.lnk'   # nombre anterior de la app
if (Test-Path $anterior) { Remove-Item $anterior }
if ($Activar) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($acceso)
    $lnk.TargetPath = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\iniciar.ps1`" -SinNavegador"
    $lnk.WorkingDirectory = $Proyecto
    $lnk.Description = 'Inicia CoraNotes al iniciar sesión'
    $lnk.Save()
    Write-Host "Inicio automático activado: $acceso" -ForegroundColor Green
} elseif ($Desactivar) {
    if (Test-Path $acceso) { Remove-Item $acceso; Write-Host 'Inicio automático desactivado.' -ForegroundColor Green }
    else { Write-Host 'El inicio automático no estaba activado.' }
} else {
    Write-Host 'Indicá -Activar o -Desactivar.'
    Write-Host "Estado actual: $(if (Test-Path $acceso) { 'ACTIVADO' } else { 'desactivado' })"
}

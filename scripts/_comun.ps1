# Funciones compartidas por los scripts de CoraNotes (se cargan con ". .\_comun.ps1").
$ErrorActionPreference = 'Stop'
$Proyecto = Split-Path -Parent $PSScriptRoot

function Leer-Env([string]$Clave) {
    $valorEntorno = [Environment]::GetEnvironmentVariable($Clave)
    if ($valorEntorno) { return $valorEntorno }
    $archivo = Join-Path $Proyecto '.env'
    if (-not (Test-Path $archivo)) { return $null }
    foreach ($linea in Get-Content $archivo -Encoding UTF8) {
        $l = $linea.Trim()
        if ($l -eq '' -or $l.StartsWith('#') -or -not $l.Contains('=')) { continue }
        $partes = $l.Split('=', 2)
        if ($partes[0].Trim() -eq $Clave) { return $partes[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

function Leer-EnvApp([string]$Nombre) {
    # CORANOTES_<Nombre>; se acepta también BITACORA_<Nombre> (nombre anterior de la app).
    $v = Leer-Env "CORANOTES_$Nombre"
    if ($v) { return $v }
    return (Leer-Env "BITACORA_$Nombre")
}

function Obtener-Puerto([switch]$Demo) {
    if ($Demo) { return 8766 }
    $p = Leer-EnvApp 'PORT'
    if ($p -match '^\d+$') { return [int]$p }
    return 8765
}

function Obtener-CarpetaDatos([switch]$Demo) {
    # Igual que la app: %LOCALAPPDATA%\CoraNotes; si todavía no se migró, la carpeta anterior (BitacoraIA).
    $h = if ($Demo) { Leer-EnvApp 'HOME_DEMO' } else { Leer-EnvApp 'HOME' }
    if ($h) { return $h }
    $nueva = Join-Path $env:LOCALAPPDATA $(if ($Demo) { 'CoraNotes-demo' } else { 'CoraNotes' })
    $vieja = Join-Path $env:LOCALAPPDATA $(if ($Demo) { 'BitacoraIA-demo' } else { 'BitacoraIA' })
    if (-not (Test-Path $nueva) -and (Test-Path $vieja)) { return $vieja }
    return $nueva
}

function Fijar-Modo([switch]$Demo, [int]$Puerto) {
    # Variables que lee la app (y su mascota) en este proceso y en los que inicie.
    if ($Demo) {
        $env:CORANOTES_DEMO = '1'
        $env:CORANOTES_PORT = "$Puerto"
    } else {
        Remove-Item Env:CORANOTES_DEMO -ErrorAction SilentlyContinue
    }
    Remove-Item Env:BITACORA_DEMO -ErrorAction SilentlyContinue
}

function Probar-Servidor([int]$Puerto) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Puerto/api/sesion" -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Iniciar-Oculto([string]$Exe, [string]$Argumentos) {
    # ShellExecute: el proceso hijo no hereda la consola ni las tuberías de este script.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = $Argumentos
    $psi.WorkingDirectory = $Proyecto
    $psi.UseShellExecute = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($psi)
}

$script:MotivoVenv = ''

function Venv-Funciona([string]$Py) {
    # Un .venv copiado de otra PC (o creado con un Python que ya no existe) tiene python.exe pero no arranca.
    # Se prueba dos veces y solo cuenta la salida estándar y el código de salida (stderr no es un error).
    if (-not (Test-Path $Py)) { $script:MotivoVenv = 'no existe python.exe'; return $false }
    $ErrorActionPreference = 'Continue'
    for ($intento = 1; $intento -le 2; $intento++) {
        try {
            $salida = & $Py -c 'import sys; print(sys.version_info >= (3, 11))' 2>&1
            $texto = ($salida | ForEach-Object { "$_" } | Where-Object { $_ -and $_ -notlike '*RemoteException*' }) -join ' '
            if ($LASTEXITCODE -eq 0 -and $texto -match '(^|\s)True(\s|$)') { return $true }
            $script:MotivoVenv = "código $LASTEXITCODE`: $texto"
        } catch {
            $script:MotivoVenv = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Buscar-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidatos = @(Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv*\uv.exe" -ErrorAction SilentlyContinue |
        ForEach-Object FullName) + @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")
    foreach ($c in $candidatos) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

$RuntimePortable = Join-Path $Proyecto 'runtime\python.exe'

function Es-Portable { return (Test-Path $RuntimePortable) }

function Obtener-Pythonw {
    # Intérprete sin consola para Cora: el Python incluido (versión portable) o el del .venv (desarrollo).
    foreach ($c in @((Join-Path $Proyecto 'runtime\pythonw.exe'), (Join-Path $Proyecto '.venv\Scripts\pythonw.exe'),
                     (Join-Path $Proyecto '.venv\Scripts\python.exe'))) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Preparar-Entorno {
    # Versión portable: usa el Python incluido en runtime\ (no instala ni descarga nada).
    # Desarrollo: devuelve .venv\Scripts\python.exe, creándolo o reparándolo si hace falta.
    $ErrorActionPreference = 'Continue'  # uv y pip escriben su progreso en stderr: no es un error
    if (Es-Portable) {
        if (Venv-Funciona $RuntimePortable) { return $RuntimePortable }
        Write-Host 'El Python incluido en la carpeta runtime no arranca.' -ForegroundColor Red
        Write-Host "  Motivo: $($script:MotivoVenv)"
        Write-Host '  Volvé a descomprimir el zip de CoraNotes (desbloquealo antes en Propiedades) y probá de nuevo.'
        return $null
    }
    $venv = Join-Path $Proyecto '.venv'
    $py = Join-Path $venv 'Scripts\python.exe'
    if ((Test-Path $venv) -and -not (Venv-Funciona $py)) {
        Write-Host 'El entorno .venv no funciona en esta PC (lo creó otro Python). Se vuelve a crear...' -ForegroundColor Yellow
        Write-Host "  Motivo: $($script:MotivoVenv)"
        # Se aparta (no se borra) por si el diagnóstico fuera un falso positivo; solo se guarda el último.
        $apartado = Join-Path $Proyecto '.venv.roto'
        if (Test-Path $apartado) { Remove-Item $apartado -Recurse -Force }
        Rename-Item $venv '.venv.roto'
    }
    if (-not (Test-Path $py)) {
        Write-Host 'Creando entorno virtual (.venv)... (solo la primera vez)'
        $python = Buscar-Python
        if ($python) {
            $a = @()
            if ($python.Count -gt 1) { $a += $python[1] }
            & $python[0] @a -m venv $venv | Out-Host
        } else {
            $uv = Buscar-Uv
            if (-not $uv) {
                Write-Host 'No se encontró Python 3.11 o superior. Instalalo desde https://www.python.org/downloads/ (marcá "Add python.exe to PATH") y volvé a ejecutar este script.' -ForegroundColor Red
                return $null
            }
            Write-Host 'No hay Python en el PATH: se usa uv para descargar Python 3.12 (solo la primera vez)...'
            & $uv venv --seed --python 3.12 $venv | Out-Host
        }
        if (-not (Venv-Funciona $py)) {
            Write-Host 'No se pudo crear el entorno virtual.' -ForegroundColor Red
            return $null
        }
    }
    # Instala o actualiza dependencias solo si cambió requirements.txt
    $req = Join-Path $Proyecto 'requirements.txt'
    $marca = Join-Path $venv 'requirements.sha256'
    $hash = (Get-FileHash $req -Algorithm SHA256).Hash
    if (-not (Test-Path $marca) -or (Get-Content $marca) -ne $hash) {
        Write-Host 'Instalando dependencias (puede tardar unos minutos la primera vez)...'
        & $py -m pip install --disable-pip-version-check -q -r $req | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Falló la instalación de dependencias. Revisá tu conexión a internet.' -ForegroundColor Red
            return $null
        }
        Set-Content -Path $marca -Value $hash -Encoding ascii
    }
    return $py
}

function Buscar-Python {
    $candidatos = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.13', '3.12', '3.11') { $candidatos += , @('py', "-$v") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { $candidatos += , @('python') }
    foreach ($c in $candidatos) {
        try {
            $args2 = @()
            if ($c.Count -gt 1) { $args2 += $c[1] }
            $args2 += @('-c', 'import sys; print(sys.version_info >= (3, 11))')
            $salida = & $c[0] @args2 2>$null
            if ($salida -eq 'True') { return , $c }
        } catch { }
    }
    return $null
}

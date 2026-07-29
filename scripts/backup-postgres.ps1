[CmdletBinding()]
param(
    [string]$Destination,

    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $backupDirectory = Join-Path $projectRoot "backups\postgres"
}
elseif ([System.IO.Path]::IsPathRooted($Destination)) {
    $backupDirectory = [System.IO.Path]::GetFullPath($Destination)
}
else {
    $backupDirectory = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Destination))
}

$pathRoot = [System.IO.Path]::GetPathRoot($backupDirectory)
if ($backupDirectory.TrimEnd("\", "/") -eq $pathRoot.TrimEnd("\", "/")) {
    throw "La carpeta de respaldo no puede ser la raíz de una unidad."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker no está instalado o no está disponible en PATH."
}

& docker info --format "{{.ServerVersion}}" *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop no está iniciado."
}

New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$backupDirectory = (Resolve-Path -LiteralPath $backupDirectory).Path

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $backupDirectory "bot-ofertas-$timestamp.dump"
$containerPath = "/tmp/bot-ofertas-$timestamp-$PID.dump"

Push-Location $projectRoot
try {
    $containerId = (& docker compose ps --quiet postgres).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) {
        throw "PostgreSQL no está iniciado. Ejecuta primero scripts\bot-ofertas.ps1 start."
    }

    $containerState = (& docker inspect --format "{{.State.Status}}" $containerId).Trim()
    if ($LASTEXITCODE -ne 0 -or $containerState -ne "running") {
        throw "El contenedor de PostgreSQL no está en ejecución."
    }

    try {
        Write-Host "Creando respaldo consistente de PostgreSQL..."
        & docker exec $containerId sh -ec `
            'pg_dump --format=custom --file "$1" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" && pg_restore --list "$1" >/dev/null' `
            sh $containerPath
        if ($LASTEXITCODE -ne 0) {
            throw "pg_dump o la validación con pg_restore falló."
        }

        & docker cp "${containerId}:$containerPath" $backupPath
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo copiar el respaldo desde PostgreSQL."
        }
    }
    finally {
        & docker exec $containerId rm -f -- $containerPath *> $null
    }

    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "El archivo de respaldo no fue creado."
    }

    $cutoff = (Get-Date).ToUniversalTime().AddDays(-$RetentionDays)
    $expired = Get-ChildItem -LiteralPath $backupDirectory `
        -File `
        -Filter "bot-ofertas-*.dump" |
        Where-Object {
            $_.FullName -ne $backupPath -and $_.LastWriteTimeUtc -lt $cutoff
        }

    foreach ($file in $expired) {
        Remove-Item -LiteralPath $file.FullName -Force
    }

    $backup = Get-Item -LiteralPath $backupPath
    Write-Host "Respaldo verificado: $($backup.FullName)"
    Write-Host "Tamaño: $([Math]::Round($backup.Length / 1MB, 2)) MB"
    Write-Host "Retención aplicada únicamente en esta carpeta: $RetentionDays días"
}
finally {
    Pop-Location
}

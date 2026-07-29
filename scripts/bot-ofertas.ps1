[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action = "status",

    [Parameter(Position = 1)]
    [ValidateSet("postgres", "migrations", "api", "worker", "watchdog", "backup", "dashboard")]
    [string]$Service,

    [ValidateRange(10, 5000)]
    [int]$Tail = 150,

    [switch]$Follow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$envFile = Join-Path $projectRoot ".env"

function Assert-LastExitCode {
    param([string]$Operation)

    if ($LASTEXITCODE -ne 0) {
        throw "$Operation terminó con código $LASTEXITCODE."
    }
}

function Assert-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker no está instalado o no está disponible en PATH."
    }

    & docker info --format "{{.ServerVersion}}" *> $null
    Assert-LastExitCode "La comprobación de Docker"
}

function Wait-ComposeService {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $containerId = (& docker compose ps --quiet $Name).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo consultar el servicio '$Name'."
        }
        if ($containerId) {
            $state = (& docker inspect `
                --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
                $containerId).Trim()
            if ($LASTEXITCODE -ne 0) {
                throw "No se pudo inspeccionar el servicio '$Name'."
            }
            if ($state -in @("healthy", "running")) {
                Write-Host "  OK  $Name ($state)"
                return
            }
            if ($state -in @("unhealthy", "exited", "dead")) {
                throw "El servicio '$Name' terminó en estado '$state'. Consulta los logs."
            }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    throw "El servicio '$Name' no quedó listo después de $TimeoutSeconds segundos."
}

function Start-BotOfertas {
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "Falta $envFile. Copia .env.example como .env y configura sus valores."
    }

    Write-Host "Construyendo e iniciando Bot Ofertas..."
    & docker compose up --detach --build --remove-orphans
    Assert-LastExitCode "El arranque de Docker Compose"

    Write-Host "Comprobando servicios..."
    Wait-ComposeService -Name "postgres"
    Wait-ComposeService -Name "api"
    Wait-ComposeService -Name "worker"
    Wait-ComposeService -Name "watchdog"
    Wait-ComposeService -Name "backup"
    Wait-ComposeService -Name "dashboard"

    Write-Host ""
    Write-Host "Bot Ofertas está funcionando de forma privada:"
    Write-Host "  Panel: http://localhost:3000"
    Write-Host "  API:   http://127.0.0.1:8000/docs"
}

Assert-DockerReady
Push-Location $projectRoot
try {
    switch ($Action) {
        "start" {
            Start-BotOfertas
        }
        "stop" {
            Write-Host "Deteniendo Bot Ofertas (la base de datos se conserva)..."
            & docker compose stop
            Assert-LastExitCode "La detención de Docker Compose"
        }
        "restart" {
            Write-Host "Reiniciando Bot Ofertas..."
            & docker compose stop
            Assert-LastExitCode "La detención de Docker Compose"
            Start-BotOfertas
        }
        "status" {
            & docker compose ps --all
            Assert-LastExitCode "La consulta de estado"
        }
        "logs" {
            $arguments = @("compose", "logs", "--tail", $Tail)
            if ($Follow) {
                $arguments += "--follow"
            }
            if ($Service) {
                $arguments += $Service
            }
            & docker @arguments
            Assert-LastExitCode "La consulta de logs"
        }
    }
}
finally {
    Pop-Location
}

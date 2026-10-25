# Sobe todos os serviços do MD Bank via Docker Compose (Windows).
# Uso: .\scripts\start.ps1 [-NoBuild]
param(
    [switch]$NoBuild
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error 'Docker não encontrado. Instale o Docker Desktop.'
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Docker não está em execução. Inicie o Docker Desktop.'
    exit 1
}

foreach ($envFile in 'supervisor/.env', 'agents/abrir_conta/.env', 'agents/cartao_credito/.env', 'agents/pagamentos/.env') {
    if (-not (Test-Path $envFile)) {
        Write-Warning "$envFile não encontrado (defina ANTHROPIC_API_KEY)."
    }
}

$composeArgs = @('compose', 'up', '-d')
if (-not $NoBuild) { $composeArgs += '--build' }

& docker @composeArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker compose ps

Write-Host ''
Write-Host 'Frontend React:     http://localhost:3000'
Write-Host 'Frontend Streamlit: http://localhost:9090'
Write-Host 'Supervisor:         http://localhost:8080'
Write-Host 'Logs:               docker compose logs -f'

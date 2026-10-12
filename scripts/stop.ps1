# Para e remove os containers do MD Bank (Windows).
# Uso: .\scripts\stop.ps1
$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)

docker compose down
exit $LASTEXITCODE

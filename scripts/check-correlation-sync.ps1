# Verifica se as cópias de correlation.py e observability.py estão idênticas entre os serviços.
# Cada serviço é um contexto Docker próprio, então os módulos compartilhados são duplicados.
# Uso: .\scripts\check-correlation-sync.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$groups = [ordered]@{
    'correlation.py'   = @('supervisor', 'agents/abrir_conta', 'agents/cartao_credito', 'recursos', 'frontend')
    'observability.py' = @('supervisor', 'agents/abrir_conta', 'agents/cartao_credito')
}

$divergent = 0
foreach ($file in $groups.Keys) {
    $hashes = [ordered]@{}
    foreach ($dir in $groups[$file]) {
        $path = Join-Path $dir $file
        $hashes[$path] = (Get-FileHash -Algorithm SHA256 -Path $path).Hash
    }

    $unique = $hashes.Values | Select-Object -Unique
    if (@($unique).Count -gt 1) {
        Write-Host "DIVERGENTE: $file" -ForegroundColor Red
        $hashes.GetEnumerator() | ForEach-Object { Write-Host "  $($_.Value)  $($_.Key)" }
        $divergent++
    }
    else {
        Write-Host "OK: $file ($(@($groups[$file]).Count) cópias idênticas)"
    }
}

if ($divergent -gt 0) { exit 1 }
exit 0

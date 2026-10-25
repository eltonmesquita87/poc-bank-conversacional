#!/usr/bin/env bash
# Verifica se as cópias de correlation.py e observability.py estão idênticas entre os serviços.
# Cada serviço é um contexto Docker próprio, então os módulos compartilhados são duplicados.
# Uso: ./scripts/check-correlation-sync.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

declare -A groups=(
    [correlation.py]="supervisor agents/abrir_conta agents/cartao_credito agents/pagamentos recursos pix_mcp frontend"
    [observability.py]="supervisor agents/abrir_conta agents/cartao_credito agents/pagamentos"
)

divergent=0
for file in correlation.py observability.py; do
    unique=$(for dir in ${groups[$file]}; do sha256sum "$dir/$file"; done | awk '{print $1}' | sort -u | wc -l)
    if [ "$unique" -gt 1 ]; then
        echo "DIVERGENTE: $file" >&2
        for dir in ${groups[$file]}; do sha256sum "$dir/$file"; done >&2
        divergent=$((divergent + 1))
    else
        count=$(echo ${groups[$file]} | wc -w)
        echo "OK: $file ($count cópias idênticas)"
    fi
done

if [ "$divergent" -gt 0 ]; then
    exit 1
fi

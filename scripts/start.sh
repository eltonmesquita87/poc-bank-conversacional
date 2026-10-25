#!/usr/bin/env bash
# Sobe todos os serviços do MD Bank via Docker Compose (Linux/macOS).
# Uso: ./scripts/start.sh [--no-build]
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker não encontrado. Instale o Docker." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Docker não está em execução (ou sem permissão para acessá-lo)." >&2
    exit 1
fi

for env_file in supervisor/.env agents/abrir_conta/.env agents/cartao_credito/.env agents/pagamentos/.env; do
    if [ ! -f "$env_file" ]; then
        echo "AVISO: $env_file não encontrado (defina ANTHROPIC_API_KEY)." >&2
    fi
done

args=(compose up -d)
if [ "${1:-}" != "--no-build" ]; then
    args+=(--build)
fi

docker "${args[@]}"
docker compose ps

echo
echo "Frontend React:     http://localhost:3000"
echo "Frontend Streamlit: http://localhost:9090"
echo "Supervisor:         http://localhost:8080"
echo "Logs:               docker compose logs -f"

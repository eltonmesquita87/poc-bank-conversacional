#!/usr/bin/env bash
# Para e remove os containers do MD Bank (Linux/macOS).
# Uso: ./scripts/stop.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose down

import sys
from pathlib import Path

# Permite importar os módulos da raiz do serviço (domain, client, ...) sem instalar o pacote.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

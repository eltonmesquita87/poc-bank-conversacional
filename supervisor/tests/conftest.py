import sys
from pathlib import Path

# Permite importar `correlation` (módulo na raiz do serviço) sem instalar o pacote.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

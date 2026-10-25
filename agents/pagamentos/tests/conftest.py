import os
import sys
from pathlib import Path

# Permite importar os módulos da raiz do serviço (executor, agent.pagamentos...).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# init_chat_model exige uma chave no import; nenhum teste chama o LLM.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-teste-nao-usada")

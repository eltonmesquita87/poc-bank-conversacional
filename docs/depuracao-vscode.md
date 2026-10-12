# Depurando localmente com o VS Code

Como depurar os serviços do MD Bank com breakpoints no VS Code, sem Docker. Parte do ambiente descrito em [Executando localmente com UV](execucao-local-uv.md): ambientes virtuais criados, `.env` preenchidos e arquivo `hosts` configurado.

## Visão geral

O workspace [MD_BANK_IA.code-workspace](../MD_BANK_IA.code-workspace) abre cada serviço como uma pasta própria e traz as configurações de depuração na seção `launch`. Cada configuração roda o serviço sob o debugger, com o `.venv` e o IP de loopback corretos.

| Configuração | Pasta | Comando equivalente | Endereço |
|---|---|---|---|
| `recursos (MCP)` | `recursos` | `fastmcp run app.py:mcp` | `127.0.0.10:8000/mcp_gateway` |
| `abrir_conta` | `agents/abrir_conta` | `uvicorn server:app` | `127.0.0.12:8000` |
| `cartao_credito` | `agents/cartao_credito` | `uvicorn server:app` | `127.0.0.13:8000` |
| `supervisor` | `supervisor` | `uvicorn app:app` | `127.0.0.11:8000` |
| `supervisor (React)` | `supervisor` | `uvicorn app:app` | `127.0.0.1:8080` |
| `bfa` | `bfa` | `uvicorn app:app` | `127.0.0.14:8000` |
| `frontend (Streamlit)` | `frontend` | `streamlit run app.py` | `localhost:9090` |

O grupo **Backend completo** sobe `recursos`, os dois agentes, o `supervisor` e o `bfa` de uma vez, na ordem de dependência.

## Pré-requisitos

| Item | Detalhe |
|---|---|
| Ambientes virtuais | `.venv` criado em cada projeto (`uv venv` + `uv pip install -r requirements.txt`) |
| Arquivo `hosts` | Entradas de [Rede local](execucao-local-uv.md#rede-local) aplicadas |
| `.env` | `ANTHROPIC_API_KEY` em `supervisor`, `agents/abrir_conta` e `agents/cartao_credito` |
| Extensões | **Python** e **Python Debugger** (`ms-python.python`, `ms-python.debugpy`) |

O `debugpy` não precisa estar no `requirements.txt`: a extensão injeta o próprio.

## Passo a passo

### 1. Abrir o workspace

`File > Open Workspace from File...` e selecione `MD_BANK_IA.code-workspace`. Abrir só a pasta raiz não funciona: as configurações usam `${workspaceFolder:<nome>}`, que depende das pastas do workspace.

### 2. Conferir o interpretador

Em cada pasta, a barra de status deve mostrar o `.venv` dela. Se não mostrar, use `Ctrl+Shift+P` > **Python: Select Interpreter** e escolha `.venv\Scripts\python.exe` da pasta. A configuração de depuração já fixa o `python`, mas isso evita sublinhados falsos de import no editor.

### 3. Colocar breakpoints

Clique na margem esquerda da linha. Pontos úteis:

| Quero observar | Arquivo |
|---|---|
| Classificação da intenção e delegação | `supervisor/src/agents.py`, `supervisor/src/services.py` |
| Entrada/saída da API do supervisor | `supervisor/app.py` |
| Execução de uma tarefa A2A | `agents/abrir_conta/executor.py`, `agents/cartao_credito/executor.py` |
| Prompt e tools do agente | `agents/abrir_conta/agent/abrir_conta.py`, `agents/cartao_credito/agent/cartoes.py` |
| Regras de negócio (MCP) | `recursos/app.py` |
| Descoberta de agentes e tools | `bfa/discovery.py`, `bfa/mcp_discovery.py`, `bfa/registry.py` |

### 4. Iniciar a depuração

1. Abra **Run and Debug** (`Ctrl+Shift+D`).
2. Escolha **Backend completo** (ou uma configuração individual) na lista.
3. Pressione `F5`.

Cada serviço abre um terminal próprio, listado no painel **Call Stack**. Aguarde o log `Application startup complete` em todos antes de testar.

### 5. Disparar o fluxo

Com os serviços no ar, envie uma mensagem ao supervisor:

```powershell
curl.exe -X POST http://supervisor:8000/chat -H "Content-Type: application/json" -d '{\"message\": \"quero abrir uma conta\", \"session_id\": \"1\", \"client_id\": \"1\"}'
```

Ou use o chat Streamlit (configuração `frontend (Streamlit)`, http://localhost:9090). O VS Code para no primeiro breakpoint atingido, em qualquer serviço, e o painel **Call Stack** troca para o processo correspondente.

### 6. Navegar na execução

| Ação | Atalho |
|---|---|
| Continuar | `F5` |
| Passar sobre (step over) | `F10` |
| Entrar (step into) | `F11` |
| Sair (step out) | `Shift+F11` |
| Reiniciar | `Ctrl+Shift+F5` |
| Parar | `Shift+F5` |

Use os painéis **Variables**, **Watch** e a **Debug Console** para inspecionar valores e avaliar expressões.

### 7. Encerrar

`Shift+F5` para o serviço selecionado. Em um grupo composto, `stopAll` encerra todos juntos.

## Depurando um serviço isolado

Para investigar só um serviço, suba os demais em terminais com `uv run` (como em [Executando localmente com UV](execucao-local-uv.md#ordem-de-execução)) e rode no debugger apenas o que interessa. Respeite a ordem de dependência e não rode a mesma instância duas vezes: o IP:porta ficaria em uso.

## Frontend React (frontend2)

O React chama `http://localhost:8080/` direto do navegador. Para depurar o backend a partir dele:

1. Inicie a configuração **supervisor (React)** (`127.0.0.1:8080`), além do **Backend completo**.
2. Suba o React com `npm start` em `frontend2`.
3. Para depurar o JavaScript, use uma configuração `chrome` apontando para `http://localhost:3000` ou as DevTools do navegador.

## Observações importantes

- **Sem `--reload`**: o reloader do uvicorn cria um subprocesso e os breakpoints não são atingidos de forma confiável. As configurações de depuração rodam sem ele. Para hot reload, use os comandos da [doc de execução local](execucao-local-uv.md).
- **Timeout entre serviços**: parar em um breakpoint faz o chamador (por exemplo, o supervisor aguardando o agente) estourar o timeout. Para só observar valores sem pausar, use **logpoints** (botão direito na margem > *Add Logpoint*).
- **Código de terceiros**: o `justMyCode` está desligado em `recursos (MCP)` para permitir entrar no FastMCP. Nas demais, deixe o padrão (ligado) e desative por configuração quando precisar ver bibliotecas.
- **`.env`**: cada serviço carrega o seu `.env` com `load_dotenv()`, a partir do `cwd` definido na configuração.

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `Unable to find ${workspaceFolder:...}` | Workspace aberto pela pasta, não pelo `.code-workspace` | Abra o `MD_BANK_IA.code-workspace` |
| `getaddrinfo failed` | Entradas do `hosts` ausentes | Aplique o bloco de [Rede local](execucao-local-uv.md#rede-local) |
| `No module named uvicorn` / `fastmcp` | `.venv` sem dependências | `uv pip install -r requirements.txt` na pasta |
| Breakpoint cinza (não verificado) | Código executado em outro processo | Use a configuração do serviço que contém o arquivo |
| `Address already in use` | Serviço já rodando em terminal ou instância duplicada | Encerre o outro processo antes de depurar |
| Erro 401 / `ANTHROPIC_API_KEY` ausente | `.env` ausente ou inválido | Confira os três `.env` |
| `bfa` com `/skills` vazio | Subiu antes dos agentes ou do `recursos` | Reinicie só o `bfa` |

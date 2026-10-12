# Executando localmente com UV (sem Docker)

Como subir cada serviço direto na máquina (Windows / PowerShell) usando o [UV](https://docs.astral.sh/uv/). Para rodar com Docker, veja [Executando com Docker](execucao-docker.md).

## Pré-requisitos

| Item | Detalhe |
|---|---|
| UV | `uv --version` |
| Node.js + npm | Apenas para o `frontend2` (React) |
| Chave da OpenAI | `OPENAI_API_KEY` nos `.env` de `supervisor`, `agents/abrir_conta` e `agents/cartao_credito` |
| Administrador | Uma vez, para editar o arquivo `hosts` (veja [Rede local](#rede-local)) |

## Serviços

| Pasta | Serviço | Comando |
|---|---|---|
| `recursos` | Servidor MCP (FastMCP) | `fastmcp run` |
| `agents/abrir_conta` | Agente A2A de abertura de conta | `uvicorn server:app` |
| `agents/cartao_credito` | Agente A2A de cartão de crédito | `uvicorn server:app` |
| `supervisor` | Supervisor (FastAPI, AG-UI) | `uvicorn app:app` |
| `bfa` | Registro e descoberta (FastAPI) | `uvicorn app:app` |
| `frontend` | Chat Streamlit | `streamlit run` |
| `frontend2` | Chat React (AG-UI) | `npm start` |

## Instalar as dependências

Cada projeto tem o seu próprio ambiente virtual (`.venv`) e `requirements.txt`. Uma vez por projeto, a partir da raiz do repositório:

```powershell
foreach ($d in "recursos","agents\abrir_conta","agents\cartao_credito","bfa","frontend","supervisor") {
    Push-Location $d
    uv venv
    uv pip install -r requirements.txt
    Pop-Location
}
```

Para instalar um projeto só:

```powershell
cd bfa
uv venv
uv pip install -r requirements.txt
```

Observações:

- Os Dockerfiles usam Python 3.13. Para o mesmo comportamento local, crie o ambiente com `uv venv --python 3.13`.
- O aviso `Failed to hardlink files` é inofensivo. Para suprimi-lo, use `--link-mode=copy`.
- `uv run --no-project ...` usa automaticamente o `.venv` da pasta atual, então não é preciso ativar o ambiente. Se preferir ativar: `.venv\Scripts\Activate.ps1`.

## Rede local

O código tem URLs fixas com os nomes de serviço do Docker, sempre na porta 8000:

```text
http://recursos:8000/mcp_gateway
http://abrir_conta_agent:8000
http://cartao_credito_agent:8000
http://supervisor:8000/chat
```

Sem Docker esses nomes não existem, e os serviços não podem compartilhar a porta 8000 em `127.0.0.1`. A solução é dar a cada nome um IP de loopback próprio (todo o bloco `127.0.0.0/8` é local no Windows) e subir cada serviço nesse IP, na porta 8000. Nenhuma alteração de código é necessária.

**Edite o arquivo `hosts` uma única vez**, em um PowerShell aberto como Administrador:

```powershell
Add-Content C:\Windows\System32\drivers\etc\hosts @"
127.0.0.10 recursos
127.0.0.11 supervisor
127.0.0.12 abrir_conta_agent
127.0.0.13 cartao_credito_agent
127.0.0.14 bfa
"@
```

| Nome | IP local | Porta |
|---|---|---|
| recursos | 127.0.0.10 | 8000 |
| supervisor | 127.0.0.11 | 8000 |
| abrir_conta_agent | 127.0.0.12 | 8000 |
| cartao_credito_agent | 127.0.0.13 | 8000 |
| bfa | 127.0.0.14 | 8000 |
| frontend (Streamlit) | localhost | 9090 |
| frontend2 (React) | localhost | 3000 |

## Ordem de execução

Abra um terminal PowerShell por serviço, a partir da raiz do repositório, nesta ordem. O `bfa` consulta os demais ao iniciar.

1. `recursos` (MCP)
2. `agents/abrir_conta` e `agents/cartao_credito`
3. `supervisor`
4. `bfa`
5. `frontend` e/ou `frontend2`

### 1. recursos (servidor MCP)

```powershell
cd recursos
uv run --no-project fastmcp run app.py:mcp --transport http --host 127.0.0.10 --port 8000 --path /mcp_gateway
```

Endpoint MCP: `http://recursos:8000/mcp_gateway`

### 2. agents/abrir_conta

```powershell
cd agents\abrir_conta
uv run --no-project uvicorn server:app --host 127.0.0.12 --port 8000 --reload
```

Requer `OPENAI_API_KEY` em `agents\abrir_conta\.env` e o `recursos` no ar.

### 3. agents/cartao_credito

```powershell
cd agents\cartao_credito
uv run --no-project uvicorn server:app --host 127.0.0.13 --port 8000 --reload
```

Requer `OPENAI_API_KEY` em `agents\cartao_credito\.env` e o `recursos` no ar.

### 4. supervisor

```powershell
cd supervisor
uv run --no-project uvicorn app:app --host 127.0.0.11 --port 8000 --reload
```

Requer `OPENAI_API_KEY` em `supervisor\.env` e os dois agentes no ar. Teste:

```powershell
curl.exe -X POST http://supervisor:8000/chat -H "Content-Type: application/json" -d '{\"message\": \"quero abrir uma conta\", \"session_id\": \"1\", \"client_id\": \"1\"}'
```

### 5. bfa

```powershell
cd bfa
uv run --no-project uvicorn app:app --host 127.0.0.14 --port 8000 --reload
```

Ao iniciar, descobre os agentes e as tools do MCP. Endpoints:

- `http://bfa:8000/skills`
- `http://bfa:8000/resolve?query=abrir conta`
- `http://bfa:8000/resolve/agents?query=cartao`

### 6. frontend (Streamlit)

```powershell
cd frontend
uv run --no-project streamlit run app.py --server.port 9090
```

Acesse http://localhost:9090. Chama `http://supervisor:8000/chat`.

### 7. frontend2 (React, AG-UI)

```powershell
cd frontend2
npm install    # só na primeira vez
npm start
```

Acesse http://localhost:3000.

O React chama `http://localhost:8080/` direto do navegador (`frontend2/src/ChatPage.jsx`). Como o supervisor local está em `127.0.0.11:8000`, suba uma segunda instância dele na porta 8080 só para o React:

```powershell
cd supervisor
uv run --no-project uvicorn app:app --host 127.0.0.1 --port 8080 --reload
```

## Parar os serviços

`Ctrl+C` em cada terminal.

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `getaddrinfo failed` / host não encontrado | Entradas do `hosts` ausentes | Aplique o bloco de [Rede local](#rede-local) |
| `Connection refused` em `recursos:8000` | Servidor MCP não foi iniciado | Suba o `recursos` primeiro |
| `bfa` inicia mas `/skills` vem vazio | Agentes ou `recursos` subiram depois do `bfa` | Reinicie o `bfa` |
| Erro 401 / `OPENAI_API_KEY` ausente | `.env` ausente ou inválido no serviço | Confira os três `.env` |
| Porta em uso | Outro processo no mesmo IP:porta | Encerre o processo ou mude o IP/porta |
| `fastmcp` não é reconhecido | Comando fora do ambiente | Use `uv run --no-project fastmcp ...` dentro de `recursos` |

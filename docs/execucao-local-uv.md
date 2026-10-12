# Executando localmente com UV (sem Docker)

Como subir cada serviço direto na máquina (Windows / PowerShell) usando o [UV](https://docs.astral.sh/uv/). Para rodar com Docker, veja [Executando com Docker](execucao-docker.md).

## Pré-requisitos

| Item | Detalhe |
|---|---|
| UV | `uv --version` |
| Node.js + npm | Apenas para o `frontend2` (React) |
| Chave da Anthropic | `ANTHROPIC_API_KEY` nos `.env` de `supervisor`, `agents/abrir_conta` e `agents/cartao_credito` |
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

Requer `ANTHROPIC_API_KEY` em `agents\abrir_conta\.env` e o `recursos` no ar.

### 3. agents/cartao_credito

```powershell
cd agents\cartao_credito
uv run --no-project uvicorn server:app --host 127.0.0.13 --port 8000 --reload
```

Requer `ANTHROPIC_API_KEY` em `agents\cartao_credito\.env` e o `recursos` no ar.

### 4. supervisor

```powershell
cd supervisor
uv run --no-project uvicorn app:app --host 127.0.0.11 --port 8000 --reload
```

Requer `ANTHROPIC_API_KEY` em `supervisor\.env` e os dois agentes no ar. Teste:

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

## Subir tudo em segundo plano (script)

Alternativa aos sete terminais: inicia os serviços sem janela, chamando o `python.exe` de cada `.venv` direto, com os logs em uma pasta. Não usa `--reload`. A partir da raiz do repositório:

```powershell
$root = (Get-Location).Path
$log  = "$root\logs"
New-Item -ItemType Directory -Force $log | Out-Null

$svc = @(
  @{ n = "recursos";       d = "recursos";              a = "-m fastmcp.cli run app.py:mcp --transport http --host 127.0.0.10 --port 8000 --path /mcp_gateway" },
  @{ n = "abrir_conta";    d = "agents\abrir_conta";    a = "-m uvicorn server:app --host 127.0.0.12 --port 8000" },
  @{ n = "cartao_credito"; d = "agents\cartao_credito"; a = "-m uvicorn server:app --host 127.0.0.13 --port 8000" },
  @{ n = "supervisor";     d = "supervisor";            a = "-m uvicorn app:app --host 127.0.0.11 --port 8000" },
  @{ n = "bfa";            d = "bfa";                   a = "-m uvicorn app:app --host 127.0.0.14 --port 8000" },
  @{ n = "frontend";       d = "frontend";              a = "-m streamlit run app.py --server.port 9090 --server.headless true" }
)

foreach ($s in $svc) {
  $p = "$root\$($s.d)"
  Start-Process -FilePath "$p\.venv\Scripts\python.exe" -ArgumentList $s.a `
    -WorkingDirectory $p -WindowStyle Hidden `
    -RedirectStandardOutput "$log\$($s.n).out.log" `
    -RedirectStandardError  "$log\$($s.n).err.log"
}
```

| Serviço | Pasta | Argumentos do `python.exe` do `.venv` |
|---|---|---|
| recursos | `recursos` | `-m fastmcp.cli run app.py:mcp --transport http --host 127.0.0.10 --port 8000 --path /mcp_gateway` |
| abrir_conta | `agents\abrir_conta` | `-m uvicorn server:app --host 127.0.0.12 --port 8000` |
| cartao_credito | `agents\cartao_credito` | `-m uvicorn server:app --host 127.0.0.13 --port 8000` |
| supervisor | `supervisor` | `-m uvicorn app:app --host 127.0.0.11 --port 8000` |
| bfa | `bfa` | `-m uvicorn app:app --host 127.0.0.14 --port 8000` |
| frontend | `frontend` | `-m streamlit run app.py --server.port 9090 --server.headless true` |

Observações:

- Use `-m fastmcp.cli`, e não `-m fastmcp`: `fastmcp` é um pacote e não pode ser executado diretamente.
- O `bfa` consulta os demais serviços ao iniciar. Se subir antes dos agentes ou do `recursos`, reinicie só o `bfa`.
- O `.env` de cada serviço é lido na subida. Ao trocar a `ANTHROPIC_API_KEY`, reinicie o serviço.
- Adicione `logs/` ao `.gitignore`.

### Verificar se os serviços estão funcionais

Aguarde cerca de 15 segundos e confira cada endpoint:

```powershell
# agent cards dos agentes (200)
Invoke-WebRequest http://abrir_conta_agent:8000/.well-known/agent.json
Invoke-WebRequest http://cartao_credito_agent:8000/.well-known/agent.json

# registro do bfa: deve listar abrir_conta e cartao_credito (200)
Invoke-WebRequest http://bfa:8000/skills

# supervisor (200)
Invoke-WebRequest http://supervisor:8000/docs

# frontend Streamlit (200)
Invoke-WebRequest http://localhost:9090

# servidor MCP: 406 é o esperado para um GET simples, indica que está no ar
Invoke-WebRequest http://recursos:8000/mcp_gateway

# fluxo completo: frontend -> supervisor -> agente -> MCP -> LLM
Invoke-RestMethod -Method Post http://supervisor:8000/chat -ContentType 'application/json' `
  -Body '{"message":"quero abrir uma conta","session_id":"1","client_id":"1"}'
```

| Resultado | Significado |
|---|---|
| `/chat` retorna 200 com resposta | Fluxo completo funcionando |
| 500 com `getaddrinfo failed` | Entradas do `hosts` ausentes |
| 500 com `429` ou `credit balance is too low` | Chave da Anthropic sem créditos: adicione créditos ou troque a chave e reinicie o serviço |
| `/skills` retorna `{}` | `bfa` subiu antes dos agentes: reinicie o `bfa` |

### Encerrar

Localiza os processos pela linha de comando (`uvicorn`, `fastmcp.cli` e `streamlit`) e os encerra:

```powershell
# lista e encerra
$procs = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'uvicorn (app|server):app|fastmcp\.cli|streamlit run' -and
  $_.CommandLine -match 'MD_BANK_IA|127\.0\.0\.|--server\.port 9090'
}
$procs | ForEach-Object { "{0} {1}" -f $_.ProcessId, $_.CommandLine }
$procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# confirma que nada ficou rodando (deve listar zero processos e nenhuma porta)
Start-Sleep 3
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'uvicorn (app|server):app|fastmcp\.cli|streamlit run' } |
  ForEach-Object { $_.ProcessId }
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -in 8000,8080,9090 } | Select-Object LocalAddress, LocalPort
```

Observações:

- Cada serviço aparece em **dois** processos: o launcher do `.venv` e o Python real. Por isso a listagem mostra o dobro de linhas (12 para os 6 serviços).
- O segundo filtro (`MD_BANK_IA|127.0.0.|--server.port 9090`) evita encerrar outros `uvicorn` ou `streamlit` da máquina que não sejam deste projeto.
- Serviços iniciados em terminais com `uv run` também são encerrados pelo comando, mas `Ctrl+C` no terminal é mais limpo.

## Depuração

O workspace `MD_BANK_IA.code-workspace` traz configurações de depuração para cada serviço, com o `.venv` e o IP de loopback corretos.

1. Abra o `MD_BANK_IA.code-workspace` no VS Code.
2. Em **Run and Debug** (`Ctrl+Shift+D`), escolha **Backend completo** ou o serviço desejado.
3. Pressione `F5` e dispare o fluxo (`curl` do supervisor ou o frontend).

As configurações rodam sem `--reload`, pois o reloader do uvicorn impede que os breakpoints sejam atingidos. Passo a passo completo, uso com o React e problemas comuns em [Depurando no VS Code](depuracao-vscode.md).

## Parar os serviços

`Ctrl+C` em cada terminal.

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `getaddrinfo failed` / host não encontrado | Entradas do `hosts` ausentes | Aplique o bloco de [Rede local](#rede-local) |
| `Connection refused` em `recursos:8000` | Servidor MCP não foi iniciado | Suba o `recursos` primeiro |
| `bfa` inicia mas `/skills` vem vazio | Agentes ou `recursos` subiram depois do `bfa` | Reinicie o `bfa` |
| Erro 401 / `ANTHROPIC_API_KEY` ausente | `.env` ausente ou inválido no serviço | Confira os três `.env` |
| Porta em uso | Outro processo no mesmo IP:porta | Encerre o processo ou mude o IP/porta |
| `429` ou `credit balance is too low` | Conta da `ANTHROPIC_API_KEY` sem créditos | Adicione créditos ou troque a chave e reinicie o serviço |
| `'fastmcp' is a package and cannot be directly executed` | Uso de `python -m fastmcp` | Use `python -m fastmcp.cli` ou `uv run fastmcp` |
| `fastmcp` não é reconhecido | Comando fora do ambiente | Use `uv run --no-project fastmcp ...` dentro de `recursos` |

# Executando com Docker

Fluxo recomendado: sobe todos os serviços com um único comando, sem instalar Python ou Node na máquina. Para rodar sem Docker, veja [Executando localmente com UV](execucao-local-uv.md).

## Pré-requisitos

| Item | Detalhe |
|---|---|
| Docker Desktop | Com Docker Compose v2 (`docker compose`). No Windows, use o backend WSL 2 |
| Chave da OpenAI | Usada com o modelo `gpt-4o` pelo supervisor e pelos dois agentes |
| Portas livres | 3000, 8080, 8081, 8082, 8083, 8084 e 9090 |
| Git | Para clonar o repositório |

## Passo a passo

**1. Clone o repositório e entre na pasta**

```bash
git clone <url-do-repositorio>
cd MD_BANK_IA
git checkout feature/modulo1
```

**2. Crie o arquivo `.env` em três serviços**

O código lê `OPENAI_API_KEY` com `load_dotenv()`, e o `docker-compose.yml` não define `env_file`. Por isso o arquivo precisa existir **dentro de cada pasta** abaixo (a pasta é montada em `/app` no container):

- `supervisor/.env`
- `agents/abrir_conta/.env`
- `agents/cartao_credito/.env`

Conteúdo, o mesmo nos três:

```env
OPENAI_API_KEY=sk-...sua-chave...
```

Atalho (PowerShell):

```powershell
$k = "OPENAI_API_KEY=sk-...sua-chave..."
"supervisor", "agents/abrir_conta", "agents/cartao_credito" | ForEach-Object { Set-Content "$_/.env" $k }
```

> **Atenção:** o `.gitignore` do projeto não ignora `.env`. Adicione `.env` ao `.gitignore` antes de commitar, para não vazar a chave.

**3. Suba os containers**

```bash
docker compose up --build
```

O primeiro build leva alguns minutos (instala dependências Python e roda `npm install` do frontend2). Para rodar em segundo plano, use `docker compose up --build -d`.

**4. Aguarde a inicialização**

Os serviços não têm healthcheck. Espere os logs mostrarem `Application startup complete` para `supervisor`, `abrir_conta_agent` e `cartao_credito_agent`, e a compilação do `frontend-ag-ui`. Se o `bfa` logar erros de conexão no início, é esperado: ele tenta de novo.

**5. Acesse as interfaces**

| Interface | URL | Quando usar |
|---|---|---|
| Frontend React (AG-UI) | http://localhost:3000 | Chat com streaming e painel de state |
| Frontend Streamlit | http://localhost:9090 | Chat simples, resposta síncrona |

**6. Converse com o assistente**

Use os exemplos de [Exemplos de conversa](exemplos-de-conversa.md).

## Portas e endpoints

| Serviço | Porta no host | Endpoint útil |
|---|---|---|
| frontend-ag-ui (React) | 3000 | `/` |
| frontend (Streamlit) | 9090 | `/` |
| supervisor | 8080 | `POST /` (AG-UI), `POST /chat` (REST), `/docs` |
| abrir_conta_agent | 8081 | `/.well-known/agent-card.json` |
| cartao_credito_agent | 8082 | `/.well-known/agent-card.json` |
| bfa | 8083 | `/docs` |
| recursos (MCP) | 8084 | `/mcp_gateway` |

## Testando sem frontend

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "quero abrir uma conta", "session_id": "1", "client_id": "1"}'
```

## Operação do dia a dia

```bash
docker compose logs -f supervisor      # logs de um serviço
docker compose restart supervisor      # reinicia um serviço
docker compose down                    # para e remove os containers
docker compose build --no-cache        # rebuild completo
```

O código é montado por volume e os serviços rodam com `--reload`, então alterações em `.py` e `.jsx` são aplicadas sem rebuild. Mudanças em `requirements.txt` ou `package.json` exigem `docker compose up --build`.

Os dados de contas e cartões ficam em `recursos/db.json`. Para zerar o ambiente, pare os containers e apague esse arquivo.

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| Erro 401 / `invalid_api_key` nos logs | `.env` ausente ou chave inválida em algum dos três serviços | Confira os três `.env` e rode `docker compose restart` |
| `port is already allocated` | Porta em uso no host | Libere a porta ou altere o mapeamento em `docker-compose.yml` |
| Frontend React não alcança o supervisor | O `frontend2` chama `http://localhost:8080/` direto do browser | Confirme que o supervisor está de pé na 8080 |
| Agente "esquece" ou mistura dados entre conversas | Memória compartilhada (`thread_id="1"`); veja os [pontos de atenção](arquitetura.md#pontos-de-atenção) | Reinicie o `supervisor` e os agentes |
| Mudança de código não reflete no frontend2 | Polling do hot reload no Windows | Aguarde alguns segundos ou reinicie `frontend-ag-ui` |

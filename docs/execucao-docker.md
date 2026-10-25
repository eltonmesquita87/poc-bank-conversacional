# Executando com Docker

Fluxo recomendado: sobe todos os serviços com um único comando, sem instalar Python ou Node na máquina. Para rodar sem Docker, veja [Executando localmente com UV](execucao-local-uv.md).

## Pré-requisitos

| Item | Detalhe |
|---|---|
| Docker Desktop | Com Docker Compose v2 (`docker compose`). No Windows, use o backend WSL 2 |
| Chave da Anthropic | Usada com o modelo `claude-haiku-5-5` pelo supervisor e pelos dois agentes |
| Portas livres | 3000, 8080, 8081, 8082, 8083, 8084, 8085, 8086 e 9090 |
| `pix-service` (só para o Pix) | Repositório separado, **fora** deste compose. Deve estar no ar no host, por padrão em `http://localhost:8089`. Sem ele, o resto funciona e as tools de Pix respondem "serviço Pix indisponível" |
| Git | Para clonar o repositório |

## Passo a passo

**1. Clone o repositório e entre na pasta**

```bash
git clone <url-do-repositorio>
cd MD_BANK_IA
git checkout feature/modulo1
```

**2. Crie o arquivo `.env` em quatro serviços**

O código lê `ANTHROPIC_API_KEY` com `load_dotenv()`, e o `docker-compose.yml` não define `env_file`. Por isso o arquivo precisa existir **dentro de cada pasta** abaixo (a pasta é montada em `/app` no container):

- `supervisor/.env`
- `agents/abrir_conta/.env`
- `agents/cartao_credito/.env`
- `agents/pagamentos/.env`

Conteúdo, o mesmo nos três:

```env
ANTHROPIC_API_KEY=sk-ant-...sua-chave...
```

Atalho (PowerShell):

```powershell
$k = "ANTHROPIC_API_KEY=sk-ant-...sua-chave..."
"supervisor", "agents/abrir_conta", "agents/cartao_credito" | ForEach-Object { Set-Content "$_/.env" $k }
```

> **Atenção:** o `.gitignore` do projeto não ignora `.env`. Adicione `.env` ao `.gitignore` antes de commitar, para não vazar a chave.

**3. Suba os containers**

Use o script da sua plataforma (veja [Scripts de automação](#scripts-de-automação)):

```powershell
# Windows (PowerShell)
.\scripts\start.ps1
```

```bash
# Linux / macOS
./scripts/start.sh
```

Ou, direto pelo Compose:

```bash
docker compose up --build
```

O primeiro build leva alguns minutos (instala dependências Python e roda `npm install` do frontend2). Para rodar em segundo plano, use `docker compose up --build -d` (os scripts já fazem isso).

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
| pagamentos_agent | 8086 | `/.well-known/agent-card.json` |
| bfa | 8083 | `/docs` |
| recursos (MCP) | 8084 | `/mcp_gateway` |
| pix_mcp (MCP) | 8085 | `/mcp_gateway`, `/tools` |

## Testando sem frontend

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "quero abrir uma conta", "session_id": "1", "client_id": "1"}'
```

## Scripts de automação

A pasta [scripts](../scripts) tem atalhos para subir e parar todos os serviços. Podem ser executados de qualquer diretório.

| Ação | Windows (PowerShell) | Linux / macOS |
|---|---|---|
| Iniciar (com build) | `.\scripts\start.ps1` | `./scripts/start.sh` |
| Iniciar sem rebuild | `.\scripts\start.ps1 -NoBuild` | `./scripts/start.sh --no-build` |
| Parar e remover containers | `.\scripts\stop.ps1` | `./scripts/stop.sh` |

O que o `start` faz:

1. Confere se o Docker está instalado e em execução.
2. Avisa se algum dos três `.env` (com `ANTHROPIC_API_KEY`) não existir.
3. Executa `docker compose up -d` (com `--build`, salvo `-NoBuild` / `--no-build`).
4. Exibe o status dos containers e as URLs de acesso.

O `stop` executa `docker compose down`. Os dados em `recursos/db.json` são preservados.

> **Linux / macOS:** se o script não tiver permissão de execução, rode `chmod +x scripts/*.sh`. No Windows, se a política de execução bloquear o `.ps1`, use `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1`.

## Operação do dia a dia

```bash
docker compose logs -f supervisor      # logs de um serviço
docker compose restart supervisor      # reinicia um serviço
docker compose down                    # para e remove os containers
docker compose build --no-cache        # rebuild completo
```

O código é montado por volume e os serviços rodam com `--reload`, então alterações em `.py` e `.jsx` são aplicadas sem rebuild. Mudanças em `requirements.txt` ou `package.json` exigem `docker compose up --build`.

Os dados de contas e cartões ficam em `recursos/db.json`. Para zerar o ambiente, pare os containers e apague esse arquivo.

### Pix

- O `pix_mcp` chama o `pix-service` em `PIX_SERVICE_URL`. O compose usa `http://host.docker.internal:8089` (porta do `application.yml` do `pix-service`; o README dele diz 8080, veja [Pagamentos Pix](pagamentos-pix.md)). Para outro endereço, exporte a variável antes do `docker compose up` ou coloque-a em um `.env` na raiz.
- O vínculo CPF → carteira Pix fica em `pix_mcp/pix_db.json` (contém CPF em texto claro; está no `.gitignore`). Para zerar, pare o `pix_mcp` e apague o arquivo. Isso **não** apaga as carteiras no `pix-service`.
- O `pix_mcp` só cria carteira para quem já tem conta em `recursos`.
- O `pix_mcp/.env` é opcional no Docker (modelo em `pix_mcp/.env.example`). Para produção, defina `PIX_USER_ID_SECRET`.

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| Erro 401 / `invalid_api_key` nos logs | `.env` ausente ou chave inválida em algum dos quatro serviços | Confira os quatro `.env` e rode `docker compose restart` |
| Tools de Pix respondem "serviço Pix indisponível" | `pix-service` fora do ar ou em outra porta | Suba o `pix-service` no host e confira `PIX_SERVICE_URL`; veja `docker compose logs pix_mcp` (eventos `pix.error`) |
| `port is already allocated` | Porta em uso no host | Libere a porta ou altere o mapeamento em `docker-compose.yml` |
| Frontend React não alcança o supervisor | O `frontend2` chama `http://localhost:8080/` direto do browser | Confirme que o supervisor está de pé na 8080 |
| Agente "esquece" ou mistura dados entre conversas | Memória compartilhada (`thread_id="1"`); veja os [pontos de atenção](arquitetura.md#pontos-de-atenção) | Reinicie o `supervisor` e os agentes |
| Mudança de código não reflete no frontend2 | Polling do hot reload no Windows | Aguarde alguns segundos ou reinicie `frontend-ag-ui` |

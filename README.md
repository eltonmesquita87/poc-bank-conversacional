# MD Bank

Assistente bancário conversacional **multi-agente** de um banco digital fictício (PoC). Abre contas, emite cartões de crédito e consulta dados por CPF, usando **AG-UI** (usuário ↔ agente), **A2A** (agente ↔ agente) e **MCP** (agente ↔ ferramentas).

## Documentação

| Documento | Conteúdo |
|---|---|
| [Executando com Docker](docs/execucao-docker.md) | Pré-requisitos, passo a passo, portas, operação e problemas comuns |
| [Executando localmente com UV](docs/execucao-local-uv.md) | Rodar cada serviço sem Docker, com ambiente virtual por projeto |
| [Depurando no VS Code](docs/depuracao-vscode.md) | Breakpoints nos serviços locais, com configurações prontas no workspace |
| [Exemplos de conversa](docs/exemplos-de-conversa.md) | Fluxo completo e frases para testar o roteador |
| [Arquitetura](docs/arquitetura.md) | Diagramas C4, integrações, fluxo principal, pontos de atenção e próximos passos |

## Visão geral

```text
Cliente ──AG-UI/REST──► supervisor ──A2A──► agentes (abrir_conta, cartao_credito) ──MCP──► recursos (db.json)
```

| Serviço | Pasta | Papel | Porta (Docker) |
|---|---|---|---|
| frontend (Streamlit) | [frontend](frontend) | Chat simples, resposta síncrona | 9090 |
| frontend2 (React) | [frontend2](frontend2) | Chat com streaming e painel de state | 3000 |
| supervisor | [supervisor](supervisor) | Classifica a intenção, delega e agrega | 8080 |
| abrir_conta | [agents/abrir_conta](agents/abrir_conta) | Especialista em abertura de conta | 8081 |
| cartao_credito | [agents/cartao_credito](agents/cartao_credito) | Especialista em cartões | 8082 |
| bfa | [bfa](bfa) | Registro unificado de agentes e tools | 8083 |
| recursos | [recursos](recursos) | Servidor MCP com as regras de negócio | 8084 |

## Início rápido

Requer Docker Desktop e uma chave da Anthropic.

```bash
# 1. coloque ANTHROPIC_API_KEY=sk-... em supervisor/.env,
#    agents/abrir_conta/.env e agents/cartao_credito/.env
# 2. suba tudo
docker compose up --build
```

Acesse http://localhost:3000 (React) ou http://localhost:9090 (Streamlit). Detalhes em [Executando com Docker](docs/execucao-docker.md).

## Docker ou UV?

| | Docker | UV (local) |
|---|---|---|
| Instalação na máquina | Só Docker | Python (via uv), Node para o React |
| Configuração extra | Nenhuma | Entradas no arquivo `hosts` (admin) |
| Hot reload | Sim, por volume | Sim, `--reload` |
| Indicado para | Subir o sistema completo | Depurar um serviço isolado ([guia VS Code](docs/depuracao-vscode.md)) |

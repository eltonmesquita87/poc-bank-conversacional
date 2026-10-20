# Plano: observabilidade Langfuse nas aplicações agênticas do MDBank

## Context
O repositório tem 3 aplicações agênticas (LangChain/LangGraph + Claude Haiku), sem nenhum tracing:
- `supervisor/` — router (`src/agents.py`) + grafo LangGraph (`src/services.py`) que chama os agentes via A2A, com endpoints `/chat` e `/` (AG-UI stream) em `app.py`.
- `agents/abrir_conta/` e `agents/cartao_credito/` — agentes `create_agent` com tools MCP (`agent/*.py`), expostos via A2A (`executor.py`).

Objetivo: um trace único por pergunta do usuário, cobrindo router → chamada A2A → agente → LLM/tools, com sessão agrupada. Langfuse Cloud (decisão do usuário); sem containers novos.

## Abordagem (Langfuse Python SDK v3, OTel)
Cada serviço é um contexto Docker separado, então cada um ganha seu próprio `observability.py` (pequeno, idêntico):
- `get_langfuse_callbacks()` → `[CallbackHandler()]` se `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` existirem, senão `[]` (no-op seguro, app roda sem Langfuse).
- `flush()` no shutdown.

### Supervisor
- `src/agents.py`: `classifique_intencao_do_usuario(query, thread_id, config=None)` passa `config` (com callbacks) ao `agent.ainvoke`.
- `src/services.py`:
  - `executar_supervisor` e `executar_supervisor_stream`: abrir span raiz (`start_as_current_span`) + `propagate_attributes(session_id=thread_id, trace_name=...)`, e passar `config={"callbacks": [...]}` ao `graph.ainvoke` / router. Nos nós LangGraph, receber `config: RunnableConfig` e repassar ao router para não duplicar handlers.
  - `request_agent`: decorar com `@observe` (span "a2a.request_agent", input/output, agent_url) e enviar `trace_id`, `parent_span_id` e `session_id` em `Message.metadata` para propagar o trace via A2A.
- `app.py`: `flush()` no evento de shutdown do FastAPI.

### Agentes (abrir_conta, cartao_credito)
- `executor.py`: ler `context.message.metadata`; abrir span com `trace_context={"trace_id", "parent_span_id"}` para que o trace do agente entre sob o do supervisor; passar `session_id`.
- `agent/*.py`: `run_agent` passa `callbacks` ao `ainvoke` (captura LLM, tokens, custo e tools MCP).
- `server.py`/`app`: `flush()` no shutdown.

### Config e dependências
- `requirements.txt` dos 3 serviços: `langfuse>=3,<4` (conferir versão mínima que expõe `propagate_attributes`).
- `docker-compose.yml`: `env_file`/`environment` com `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` nos 3 serviços.
- `.env.example` (raiz, já permitido pelo .gitignore) com as variáveis; `.env` reais não são tocados nem commitados.
- `docs/arquitetura.md`: seção curta de observabilidade.

## Pontos de atenção (não alterados, só sinalizados)
- Ambos os agentes usam `thread_id="1"` fixo e o supervisor também → memória compartilhada entre usuários; com `session_id` do Langfuse isso ficaria misturado. Sugiro corrigir derivando do `thread_id` AG-UI, mas é mudança de comportamento: fica fora do escopo, a confirmar.
- Prompts/respostas bancárias (CPF etc.) vão para o Langfuse Cloud; considerar mascaramento (`mask=` no cliente) — incluo um mask simples de CPF por regex como opção.

## Verificação
1. `docker compose up --build`; sem chaves Langfuse → apps sobem e respondem normalmente (no-op).
2. Com chaves: `POST :8080/chat {"message":"quero abrir conta e pedir cartão"}`.
3. No Langfuse: um trace com router (LLM), 2 spans A2A e, aninhados, os traces dos agentes com chamadas LLM e tools MCP; tokens/custo preenchidos; mesma `session_id`.
4. Repetir via frontend AG-UI (`:3000`) para validar o caminho de streaming.
5. Derrubar o endpoint Langfuse (host inválido) → requisições do usuário não falham.

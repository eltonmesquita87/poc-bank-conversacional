# 02 — Plano: capacidades de pagamento (Pix) no MD Bank AI

> **Andamento (2026-10-24):** Fase 0 concluída, **com o contrato campo a campo validado contra [03-especificacao-tecnica-contrato.md](03-especificacao-tecnica-contrato.md)** ([docs/pagamentos-pix.md](../docs/pagamentos-pix.md)). Fase 1 concluída: máscara de e-mail/telefone/EVP em `correlation.py`, `observability._mask` delegando a ela. **Fase 2 implementada** (ver "Fase 2: como ficou" abaixo). Fases 3 e 4 pendentes.
>
> **Ajustes em relação ao plano aprovado, descobertos na Fase 1:**
> 1. **[FATO]** Os IDs de correlação são `uuid4` hifenizado (`new_id`), o mesmo formato do EVP. A máscara de EVP destruiria `correlation_id`/`conversation_id` nos metadados do Langfuse. Solução: `mask()` não toca valores de chaves de ID (`_UNMASKED_KEYS`).
> 2. `observability._mask` deixou de ter regex própria e delega para `correlation.mask` (regra única, antes duplicada).
> 3. Adicionar `pix_mcp` e `agents/pagamentos` aos grupos de `check-correlation-sync.{sh,ps1}` **fica para a Fase 2**, quando as pastas existirem (o script falharia agora).
> 4. **Ajustes vindos do doc 03 (contrato):** (a) telefone normalizado para DDD + número, não E.164; (b) erros classificados por endpoint + `error` + prefixo de `message` (sem código estável), isolados em `client.py`; (c) `message` do pix-service nunca é repassado ao LLM nem ao log (contém a chave Pix); (d) novo estado `ENVIADA_SEM_E2E` e dependência D5 (replay da resposta original, D-06); (e) 500 não é "falha segura" (D-07/D-08/AC-08): trata como `DESCONHECIDA`; (f) `Decimal` ponta a ponta (`parse_float=Decimal` na leitura, literal numérico no envio); (g) porta confirmada: 8089.
> 5. **[FATO]** Dependência de ambiente: o `pix-service` não compila no commit analisado (AC-01), então o teste ponta a ponta da Fase 2 depende de corrigi-lo (D4 em `docs/pagamentos-pix.md`). Os testes unitários do `pix_mcp` não dependem disso.

## Contexto

O MD Bank AI é uma PoC multiagente (supervisor LangGraph → agentes A2A → MCP `recursos` → `db.json`) que hoje só abre conta e emite cartão. O documento [01-arquitetura-atual.md](01-arquitetura-atual.md) descreve o `pix-service` (Java/Spring, **repositório separado**, 7 endpoints REST: carteira, chave Pix, depósito, saque, saldo atual/histórico, transferência com `Idempotency-Key`, webhook de liquidação).

Objetivo: o cliente pedir pagamentos em linguagem natural ("manda R$ 50 pra chave fulano@x.com", "qual meu saldo Pix?") e o sistema executar via `pix-service`, **seguindo os padrões já existentes** (A2A → MCP → sistema; correlation ID ponta a ponta; regra de negócio na tool, não no prompt; CPF mascarado; commits `feat - ...` / `doc - ...`).

### Decisões já tomadas com o usuário
| Decisão | Escolha |
|---|---|
| Integração | **Novo MCP server `pix_mcp`** (traduz tools em REST do pix-service). `recursos` não é alterado. |
| Escopo | Carteira + chaves Pix + saldo (F1, F2, F5, F6); transferência + status (F7–F9); depósito/saque (F3, F4). |
| pix-service | **Caixa-preta**: o plano cobre só este repo e registra contrato/premissas. Sem stub em container. |

### Fatos do repo que condicionam o desenho (verificados nesta leitura)
- Um agente = pasta `agents/<nome>/` com `server.py` (AgentCard + `A2AStarletteApplication` + `CorrelationMiddleware`), `executor.py` (`resolve_ids`, `bind`, `span`, `log_event`), `agent/<x>.py` (`create_agent` + `MultiServerMCPClient` + `load_mcp_tools`), `correlation.py`/`observability.py` copiados, Dockerfile, requirements, `.env.example` (modelo: [agents/cartao_credito](../agents/cartao_credito)).
- Registrar um agente exige **3 lugares no supervisor** ([services.py](../supervisor/src/services.py) `AGENTS` + nó + `add_edge`; [agents.py](../supervisor/src/agents.py) prompt do router) **+ BFA** (`bfa/discovery.py` `AGENT_ENDPOINTS`, `bfa/mcp_discovery.py` `MCP_ENDPOINTS`) + `docker-compose.yml` + scripts de start.
- `correlation.py` existe em 5 serviços e `observability.py` em 3; cópias **devem ser idênticas** (`scripts/check-correlation-sync.{sh,ps1}`). `mask()` só mascara CPF.
- **Bloqueador pré-existente [FATO]:** os executores chamam `run_agent(mensagem=user_text)` sem `thread_id` e o default é `"1"` ([cartoes.py:86](../agents/cartao_credito/agent/cartoes.py#L86), [executor.py:50](../agents/cartao_credito/executor.py#L50)) → memória compartilhada entre clientes. Para pagamento isso é inaceitável: o agente novo **não** pode herdar isso.
- `/chat` executa agentes em **paralelo** (`Send`) e `/` em **sequência** → "pagar sem ter conta" gera corrida se roteado junto com `abrir_conta`.

### Lacunas do contrato com o pix-service (derivadas do doc de arquitetura)
| # | Lacuna | Impacto no plano |
|---|---|---|
| L1 | **Não existe `GET` de transferência** (só os 7 endpoints; A6 devolve só `endToEndId`+`PENDING`) | "Acompanhar status" não é implementável de verdade. Plano: tool `consultar_transferencia` degradada (estado local + aviso) e **dependência externa D1**: `GET /pix/transfers/{endToEndId}`. |
| L2 | Depósito/saque **sem `Idempotency-Key`** (A3/A4) | Sem retry automático em POST financeiro; timeout ⇒ estado `DESCONHECIDO` + orientar conferir saldo. Pedir idempotência como D2. |
| L3 | Duplicidade de `Idempotency-Key` devolve **409** (não a resposta original, AC-09); saldo insuficiente também é 409 | Distinguidos pelo prefixo de `message` (`Insufficient balance` vs `Duplicate request`), validado no doc 03. `intent_id` é a chave determinística. |
| L4 | Sem autenticação/titularidade (AC-02), `userId` texto livre, sem busca de carteira por usuário | `pix_mcp` mantém o vínculo `cpf → wallet_id` e **nunca aceita `walletId` do LLM**. |
| L5 | Sem limites, sem normalização de chave, sem validar dígito de CPF (AC-14), EVP vem do cliente (RN-12) | `pix_mcp` normaliza, valida, impõe limites e **gera** o EVP. |
| L6 | Webhook público (AC-03) | O agente **nunca** recebe tool de webhook. Simulação de liquidação só por script manual de dev. |
| L7 | Porta efetiva **8089** (application.yml); README e Swagger dizem 8080 (D-10) | `PIX_SERVICE_URL` obrigatório, sem default. |

## Arquitetura alvo

```
Cliente → frontend(s) → supervisor ─A2A→ pagamentos_agent(:8086) ─MCP→ pix_mcp(:8085) ─REST→ pix-service (externo)
                                    └A2A→ abrir_conta / cartao_credito        └MCP→ recursos (verifica conta)
```

Novos containers: `pix_mcp` (FastMCP, espelha `recursos`) e `pagamentos_agent` (espelha `cartao_credito`). Skill/ID do agente: `pagamentos_pix`.

### `pix_mcp/` (novo) — camadas (cada módulo com uma responsabilidade)
- `app.py` — `FastMCP("PixService", middleware=[CorrelationMcpMiddleware()])`, `setup_logging("pix_mcp")`, tools, rota `/tools` (como [recursos/app.py:252](../recursos/app.py#L252), mas **inputSchema derivado da tool**, sem `schema_map` manual).
- `client.py` — `PixServiceClient` (httpx.AsyncClient único, timeout curto, header `X-Correlation-ID` via `outbound_headers()`, `log_event(... "pix", "client", ...)`). **Retry só em GET** (backoff), nunca em POST. Mapeia status HTTP → erros tipados.
- `domain.py` — `normalizar_chave()` (CPF só dígitos + DV, e-mail minúsculo, telefone **só DDD + número (10 a 11 dígitos)**; `+55` seria rejeitado pelo pix-service (RN-11), EVP), `Dinheiro` com `Decimal` (2 casas, `HALF_UP`, igual ao `Money` do pix-service; **nunca float**, ao contrário do `saldo: 0.0` de recursos), limites (`PIX_MAX_TRANSFER`, `PIX_MAX_DEPOSIT`, `PIX_MAX_WITHDRAW`).
- `store.py` — `pix_db.json` com `asyncio.Lock` + escrita atômica (`os.replace`); guarda `carteiras {cpf → wallet_id}` e `intents`. (O `db.json` atual não tem lock — não replicar.)
- `intents.py` — máquina de estados de operação financeira (abaixo).
- `mcp_logging.py` — cópia de [recursos/mcp_logging.py](../recursos/mcp_logging.py) (depende de fastmcp, fica fora da sincronização).
- `correlation.py` — 6ª cópia idêntica.
- `Dockerfile`/`requirements.txt` (`fastmcp`, `httpx`, `python-dotenv`) / `.env.example` (`PIX_SERVICE_URL`, `PIX_HTTP_TIMEOUT`, limites, `LOG_*`) — mesmo padrão de recursos (`fastmcp run app.py:mcp --path /mcp_gateway`).

### Tools MCP (o LLM só fala em `cpf`; `wallet_id` é resolvido internamente)
| Tool | Tipo | pix-service | Regras impostas **na tool** |
|---|---|---|---|
| `vincular_carteira_pix(cpf)` | escrita | `POST /wallets` | exige conta em `recursos` (`conta://{cpf}` via cliente MCP com headers de correlação); idempotente pelo mapa local (sob lock); `userId` = hash do CPF, não o CPF |
| `consultar_carteira_pix(cpf)` | leitura | — | retorna vínculo/chaves locais |
| `registrar_chave_pix(cpf, tipo, valor?)` | escrita | `POST /wallets/{id}/pix-keys` | chave CPF **só** se == CPF do titular; EVP gerado aqui; normaliza antes de enviar; 409 → mensagem clara |
| `consultar_saldo_pix(cpf, em?)` | leitura | `GET /wallets/{id}/balance[?at]` | `em` ISO sem fuso (pix-service usa `LocalDateTime`) |
| `preparar_transferencia(cpf, chave, valor)` | escrita local | — | valida valor/limite/saldo, normaliza chave, **cria intent** (TTL 5 min) e devolve resumo para o cliente confirmar |
| `preparar_saque(cpf, valor)` / `preparar_deposito(cpf, valor)` | escrita local | — | idem; depósito atrás de `PIX_ENABLE_DEPOSIT_SIMULATION` (AC-04: sem origem de fundos) |
| `confirmar_operacao(cpf, intent_id)` | **escrita financeira** | `POST /pix/transfers` \| `/withdraw` \| `/deposit` | ver anti-fraude abaixo |
| `cancelar_operacao(cpf, intent_id)` | escrita local | — | — |
| `consultar_transferencia(cpf, end_to_end_id)` | leitura | `GET /pix/transfers/{e2e}` **(D1)** | enquanto D1 não existir: devolve estado local + `"fonte": "local"` |

Anti-fraude / confirmação (padrão "regra na tool", per `arquitetura.md` ponto 7):
1. `confirmar_operacao` **recusa** se o `correlation_id` atual == o do `preparar_*` (a confirmação precisa ser de **outro turno** do usuário; o ID é um por turno e já chega ao MCP via `mcp_http_client_factory`). Impede o LLM de preparar+confirmar na mesma resposta.
2. Intent pertence ao `cpf`; expira em 5 min; só `PREPARADA → CONFIRMANDO` uma vez (lock + transição atômica).
3. `Idempotency-Key = intent_id` (formato `ix_<hex>`, não UUID, para não colidir com a máscara de EVP).
4. Estados: `PREPARADA → CONFIRMANDO → ENVIADA(e2e) | ENVIADA_SEM_E2E | FALHA | DESCONHECIDA(timeout/5xx)`; `CANCELADA | EXPIRADA`. `DESCONHECIDA` nunca reenvia sozinho em depósito/saque (L2); em transferência reenvio é seguro (mesma chave); se o reenvio responder 409 `Duplicate request`, a transferência já existe mas o `endToEndId` não é recuperável (D-06) ⇒ `ENVIADA_SEM_E2E`.
5. Todo retorno segue o padrão de recursos: `{"status": "...", "mensagem": ...}`, sem lançar exceção para o LLM.

### `agents/pagamentos/` (novo, :8086)
Cópia estrutural de `cartao_credito`: `server.py` (skill `pagamentos_pix`, tags `pix, transferência, saldo, chave, pagamento`, `url=http://pagamentos_agent:8000/`), `executor.py` (span `agent.pagamentos_pix`), `agent/pagamentos.py` (MCP `"pix"` → `http://pix_mcp:8000/mcp_gateway`, `load_mcp_tools(client, server="pix")`, agente com **cache** como `cartoes.py`, não rebuild por request como `abrir_conta`). Diferenças deliberadas:
- `thread_id = get_conversation_id()` (corrige o `"1"` fixo **apenas** neste agente).
- System prompt no mesmo estilo (blocos `REGRAS OBRIGATÓRIAS / FLUXO / ERROS`): usar sempre tools; nunca inventar saldo/chave; **nunca** confirmar sem mensagem explícita do cliente em turno posterior ao resumo; mostrar valor, destino mascarado e limite antes de pedir confirmação; sem conta → orientar abertura, não criar; nunca expor dados de terceiros.

### Supervisor, BFA, compose (wiring)
- `supervisor/src/services.py`: `AGENTS["pagamentos_pix"]`, `pagamentos_pix_node`, `add_node`, `add_edge(... END)`. Endurecer o stream: filtrar agentes desconhecidos do router (hoje `AGENTS[agent_name]` dá `KeyError`).
- `supervisor/src/agents.py`: incluir `pagamentos_pix` na lista/regras/exemplos do prompt. Regras novas: operação financeira **nunca** junto com `abrir_conta` no mesmo turno; sem conta ⇒ só `abrir_conta`; confirmação ("sim, confirmo") continua no `pagamentos_pix`.
- `bfa/discovery.py` + `bfa/mcp_discovery.py`: adicionar `http://pagamentos_agent:8000` e `http://pix_mcp:8000`.
- `docker-compose.yml`: serviços `pix_mcp` (8085→8000, volume `./pix_mcp`) e `pagamentos_agent` (8086→8000), `depends_on`; `pix_mcp` com `environment: PIX_SERVICE_URL` e `extra_hosts: host.docker.internal:host-gateway` (pix-service roda fora do compose); `bfa.depends_on` ampliado.
- `scripts/start.{sh,ps1}`: incluir `agents/pagamentos/.env` e `pix_mcp/.env` no aviso; mensagem das portas.
- Frontends: sem alteração de código (confirmação é texto no chat). O parsing por regex de `StateUtilPage` continua só para conta/cartão.

### Observabilidade e privacidade (extensão do que existe)
- `mask()` em `correlation.py` e `_mask` em `observability.py`: além de CPF, mascarar **e-mail, telefone e EVP (UUID com hífen)**, mantendo as cópias idênticas; adicionar `pix_mcp` e `agents/pagamentos` aos grupos de `check-correlation-sync.{sh,ps1}`.
- Novo evento no catálogo: `pix.request/response/error` (role `client`, campos `endpoint`, `http_status`, `duration_ms`) e `payment.intent` (`prepared/confirmed/cancelled/expired/unknown`, com `intent_id`, `kind`, `valor`, **sem chave em claro**). Atualizar o catálogo em `docs/arquitetura.md`.
- Corrige na origem a lacuna AC-07 do doc: o pix-service grava a chave em log/ledger; do nosso lado **não** logamos chave Pix em claro.

## Fases (cada uma entregável e revertível; commit por fase no padrão `feat - ...`)

**Fase 0 — Contrato e premissas (doc, sem código)**
- Criar `docs/pagamentos-pix.md`: contrato esperado do pix-service (tabela L1–L7, endpoints usados, formato de erro por status), dependências externas D1 (`GET` transferência), D2 (idempotência em depósito/saque), D3 (auth entre serviços), e riscos aceitos na PoC.
- **Contrato validado** com o doc 03 (corpo dos erros, DTOs, porta, regras de chave). Pendências que dependem de execução e do build do pix-service: `docs/pagamentos-pix.md` seção 6.

**Fase 1 — Fundação compartilhada**
- Estender máscara (CPF + e-mail/telefone/EVP) nas cópias; atualizar scripts de sync; testes em `supervisor/tests/test_correlation.py` e `test_observability.py` (casos novos + garantia de que `correlation_id`/`intent_id`/`endToEndId` **não** são mascarados).

**Fase 2 — Fatia vertical somente-leitura/baixo risco**
- `pix_mcp` com `client.py`, `domain.py`, `store.py` e tools `vincular_carteira_pix`, `consultar_carteira_pix`, `registrar_chave_pix`, `consultar_saldo_pix` + `/tools`.
- `agents/pagamentos` + wiring supervisor/BFA/compose/scripts.
- Teste manual: "quero ver meu saldo Pix" (com e sem conta), "cadastre minha chave CPF".

**Fase 3 — Operações financeiras com confirmação**
- `intents.py` + `preparar_*`, `confirmar_operacao`, `cancelar_operacao`, `consultar_transferencia` (degradada até D1).
- Ajustar prompts (router e agente) para o fluxo de duas etapas.

**Fase 4 — Docs e fechamento**
- Atualizar `docs/arquitetura.md` (C4 níveis 1–3 com os 2 containers novos, superfície MCP, catálogo de eventos, pontos de atenção), `README.md` (tabela de portas), `docs/execucao-docker.md`, `docs/exemplos-de-conversa.md` (Pix feliz, sem conta, saldo insuficiente, confirmação em outro turno, expiração), `docs/arquitetura-kubernetes.md` (novos Deployments/Services).
- Script de dev `scripts/simular-liquidacao.{sh,ps1}` que chama o webhook do pix-service manualmente (nunca exposto ao agente).

## Testes

Padrão atual: `pytest` por serviço (`supervisor/tests` com `conftest.py` que injeta o path). Replicar em `pix_mcp/tests/` (+ `pytest-asyncio`, `httpx.MockTransport`/`respx`, **sem** subir o Java):
- `domain`: normalização/validação de chave, DV do CPF, `Decimal`/arredondamento, limites.
- `intents`: transições, expiração, **recusa de confirmar no mesmo `correlation_id`**, intent de outro CPF, dupla confirmação concorrente (um só `POST`).
- `client`: mapeamento 400/404/409/500, timeout em POST ⇒ `DESCONHECIDA` sem retry, retry em GET, header `X-Correlation-ID` propagado.
- `store`: escrita atômica/lock sob concorrência.
- Supervisor: teste de **deriva de registro** — todo agente em `AGENTS` tem nó no grafo, entrada em `bfa/discovery.py` e menção no prompt do router (endereça o ponto de atenção nº 1).
- Teste de contrato opcional (`@pytest.mark.integration`, pulado sem `PIX_SERVICE_URL` acessível).

## Verificação ponta a ponta

1. `./scripts/check-correlation-sync.sh` → OK com `pix_mcp` e `pagamentos` nos grupos.
2. `pytest supervisor/tests pix_mcp/tests` verde.
3. `docker compose up -d --build`; `GET http://localhost:8085/tools` lista as tools com schema; `GET http://localhost:8083/skills` mostra `pagamentos_pix` (agente) e as tools `pix`.
4. Com o pix-service rodando no host e `PIX_SERVICE_URL` apontado: conversar via React (:3000) — conta → carteira → chave → "mandar R$ X para <chave>" → resumo → "confirmo" (turno seguinte) → `PENDING`; rodar `simular-liquidacao` → saldo do destino sobe.
5. Negativos: pagar sem conta (só `abrir_conta` roteado); confirmar sem preparar; confirmar no mesmo turno (recusado); valor acima do limite; reenviar confirmação (um só débito, conferir `GET balance`).
6. Rastreio: `docker compose logs --no-color --no-log-prefix | Select-String "<correlation_id>"` mostra `chat → router_llm → a2a → mcp/tool → pix.request` no mesmo ID; confirmar que nenhum CPF/e-mail/telefone/EVP aparece em claro (também no Langfuse).

## Riscos e fora de escopo
- **Aceitos na PoC (bloqueantes p/ produção):** sem autenticação do cliente (CPF informado no chat), CPF em claro em `pix_db.json`, `InMemorySaver`/`InMemoryTaskStore`, pix-service sem auth/webhook público (AC-02/03).
- **Não faremos agora:** corrigir `abrir_conta`/`cartao_credito` (`thread_id="1"`) — recomendado como follow-up; unificar as duas orquestrações; ligar o BFA ao supervisor; mudanças no pix-service; QR Code/agendamento/Pix Saque.
- **Decisão de maior custo de reversão:** `pix_mcp` consultar `recursos` via MCP para validar conta (acopla os dois). Alternativa: o agente passar `nome` e o vínculo ser a única verificação — descartada por violar "regra na tool".

## Fase 2: como ficou (implementado em 2026-10-24)

**Entregue:** `pix_mcp/` (`domain.py`, `client.py`, `store.py`, `contas.py`, `service.py`, `app.py`), `agents/pagamentos/` (agente `pagamentos_pix`, :8086), ligações no supervisor, BFA, compose e scripts. Tools: `vincular_carteira_pix`, `consultar_carteira_pix`, `registrar_chave_pix`, `consultar_saldo_pix`.

**Desvios em relação ao plano aprovado, com o motivo:**

| Desvio | Motivo ([FATO] verificado) |
|---|---|
| `service.py` entre `app.py` e `client/store/domain` | As tools só delegam; a regra fica testável sem fastmcp |
| `contas.py` tenta o CPF bruto, só dígitos e formatado | `recursos/db.json` mistura chaves só com dígitos e formatadas (999.999.999-99) e `recursos` não normaliza; sem isso, "sem conta" seria falso negativo |
| `tags=`/`meta=` nativos em vez de `annotations={tags, examples}` | O fastmcp 4.1.3 descarta campos extras de `annotations`; o `/tools` que o BFA indexa ficaria com tags vazias |
| Limite de 5 chaves por carteira e DV de CPF configurável (`PIX_VALIDAR_DV_CPF`) | O pix-service não tem limite nem valida DV; a flag existe para CPFs de demonstração |
| Filtro de agentes desconhecidos do router em `services.somente_agentes_conhecidos` | Nome inventado dava `KeyError` no stream AG-UI; fallback é `abrir_conta` (único sem ação financeira) |
| `thread_id` obrigatório no `run_agent` do agente novo (sem default) | Os outros dois usam `"1"` (mistura clientes); teste em `agents/pagamentos/tests` |
| `pix_db.json` com falha explícita se corrompido | `recursos` engole o erro e recomeça vazio, o que apagaria o vínculo das carteiras |

**Verificado (2026-10-24):**
- Testes: `pix_mcp/tests` (113; inclui o gateway contra um servidor MCP real em HTTP), `supervisor/tests` (55; inclui deriva de registro, com mutação confirmando que o teste falha), `agents/pagamentos/tests` (3). `check-correlation-sync` (7 e 4 cópias, `.sh` e `.ps1`). `docker compose config` válido.
- **Ponta a ponta sem Docker:** `pix_mcp` iniciado com o mesmo comando do Dockerfile (`fastmcp run app.py:mcp --transport http --path /mcp_gateway`), consultando o código real de `recursos` (em cópia, com contas sintéticas) e um **pix-service simulado** que segue o contrato do doc 03. 22 verificações passaram: sem conta, CPF inválido, vínculo idempotente, conta gravada formatada achada com CPF digitado só com dígitos, normalização de e-mail/telefone, EVP gerado, CPF de terceiro recusado, saldo atual e histórico, `wallet_id` ausente das respostas, `X-Correlation-ID`/`X-Conversation-ID` chegando ao pix-service. Auditoria do log do `pix_mcp`: 140 linhas JSON, **0** ocorrências de CPF, e-mail, telefone ou EVP em claro.

**NÃO verificado:**
- **Imagens Docker e compose em execução.** O `docker pull` do Docker Desktop ficou sem resposta nesta máquina (o registro responde; o daemon não baixa o `moby/buildkit`), então `docker compose build/up` não rodou. O Dockerfile do `pix_mcp` é cópia do de `recursos`, mas `host.docker.internal` e o `extra_hosts` ficam por testar.
- **O agente `pagamentos_pix` com o LLM real** (nenhuma chamada à Anthropic foi feita): prompt, roteamento do supervisor e conversa completa precisam de teste manual com a chave. O agente foi verificado até o AgentCard e o `thread_id` por conversa.
- **O `pix-service` real**: só o simulado (build quebrado, AC-01).
- Os eventos `HTTP Request: …` do `httpx` saem pelo logger do próprio httpx, sem `correlation_id` e fora do formato JSON dos demais. Não vazam PII (URLs só têm `walletId`), mas valem uma configuração de logger na Fase 3.


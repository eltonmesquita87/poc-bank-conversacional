<!-- Contrato e premissas da integração de pagamentos (Pix). Voltar: [README](../README.md). Plano completo: [refinamento/02-plano-evolucao-pagamentos.md](../refinamento/02-plano-evolucao-pagamentos.md) -->

# Pagamentos Pix: contrato com o pix-service e premissas

> **Status:** Fase 0 concluída. O `pix-service` é um repositório **separado** (Java 11 / Spring Boot 2.7, commit `698ff49`) e é tratado como **caixa-preta**. Este documento fixa o que o MD Bank AI consome e como absorve as lacunas.
> **Fontes:** [01-arquitetura-atual.md](../refinamento/01-arquitetura-atual.md) e, para o contrato campo a campo, [03-especificacao-tecnica-contrato.md](../refinamento/03-especificacao-tecnica-contrato.md) (leitura estática do `pix-service`; **nenhuma requisição foi executada**, porque o build está quebrado, AC-01). Os itens que dependem de execução estão na seção 6.

## Legenda

| Marcador | Significado |
|---|---|
| **[FATO]** | Verificado no código do `pix-service` (documentos 01 e 03, com arquivo e linha) ou neste repositório. |
| **[HIPÓTESE]** | Inferência não verificada por execução. |
| **[RECOMENDAÇÃO]** | Decisão de desenho deste repositório. |

## 1. Visão da integração

```
Cliente → frontend → supervisor ─A2A→ pagamentos_agent ─MCP→ pix_mcp ─REST→ pix-service (externo, :8089)
                                                              └MCP→ recursos (valida a conta)
```

- **[RECOMENDAÇÃO]** Só o `pix_mcp` fala com o `pix-service`. O agente nunca chama REST e **nunca** recebe `walletId`: o LLM só fala em `cpf`, e o vínculo `cpf → walletId` fica no `pix_mcp`.
- **[RECOMENDAÇÃO]** O webhook (`POST /pix/webhook`) **não** é tool. Em desenvolvimento, a liquidação é simulada por script manual (Fase 4).
- **[RECOMENDAÇÃO]** O texto de `message` dos erros do `pix-service` **nunca** é repassado ao LLM nem ao log em claro: ele pode conter a chave Pix (ex.: `Pix key not found: x@y.com`). O `pix_mcp` traduz para mensagens próprias em português.

## 2. Convenções do contrato ([FATO], doc 03 §2)

| Aspecto | Contrato efetivo | Consequência no `pix_mcp` |
|---|---|---|
| Porta e base | `8089`; `/wallets` e `/pix`, sem versão (D-10) | `PIX_SERVICE_URL` obrigatório, sem default |
| Valores | Número JSON com 2 casas, `HALF_UP`, mínimo `0.01`, sem teto | `Decimal` ponta a ponta: ler com `parse_float=Decimal` e enviar o literal numérico, nunca `float` |
| Datas | `LocalDateTime` ISO sem fuso; relógio do servidor | `em` enviado **sem offset**; o fuso do servidor é desconhecido (R-09 do doc 03). Não apresentar `timestamp` da resposta como horário de Brasília |
| IDs | `Long` (carteira); `endToEndId` = `E` + 32 hex | `intent_id` próprio no formato `ix_<hex>` (não casa com a máscara de EVP) |
| Enums | `keyType`: `CPF`, `EMAIL`, `PHONE`, `EVP`; `status`: `PENDING`, `CONFIRMED`, `REJECTED` | Validar `keyType` **antes** de enviar: valor fora do enum dá 500 (D-08) |
| Idempotência | **Só** `POST /pix/transfers` (header `Idempotency-Key`, `VARCHAR(255)`). Repetir depósito credita de novo | Sem retry automático em depósito/saque |
| Autenticação | Nenhuma, inclusive no webhook | Ver risco R1 |
| Paginação / `Location` | Não há | — |

### 2.1 Envelope de erro ([FATO], doc 03 §2.1)

```json
{ "timestamp": "2025-10-15T10:00:00.123", "status": 404, "error": "Not Found",
  "message": "Wallet not found: 999", "path": "/wallets/999/deposit" }
```

`error` ∈ {`Bad Request`, `Not Found`, `Conflict`, `Validation Failed`, `Internal Server Error`}. **Não há código de erro estável** (R-07 do doc 03): o `pix_mcp` classifica por **endpoint + `status` + `error` + prefixo de `message`**. Isso é frágil por natureza (texto livre) e por isso a classificação fica isolada em um único módulo (`client.py`), com teste de contrato por mensagem.

## 3. Endpoints consumidos ([FATO], doc 03 §4)

| Capacidade | Endpoint | Corpo | Sucesso |
|---|---|---|---|
| Criar carteira (A1) | `POST /wallets` | `{"userId": "..."}` (`@NotBlank`) | 201 `{id, userId, balance}` |
| Registrar chave (A2) | `POST /wallets/{id}/pix-keys` | `{"keyType","keyValue"}` | 201 `{id, walletId, keyType, keyValue}` |
| Depositar (A3) | `POST /wallets/{id}/deposit` | `{"amount"}` | 200 `{id, userId, balance}` (sem id da operação) |
| Sacar (A4) | `POST /wallets/{id}/withdraw` | `{"amount"}` | 200 `{id, userId, balance}` |
| Saldo (A5) | `GET /wallets/{id}/balance[?at=]` | — | 200 `{walletId, balance, timestamp}` |
| Transferir (A6) | `POST /pix/transfers` + `Idempotency-Key` | `{"fromWalletId","pixKey","amount"}` | 201 `{endToEndId, fromWalletId, toWalletId, amount, status:"PENDING"}` |
| Liquidar (A7, **fora do agente**) | `POST /pix/webhook` | `{"endToEndId","eventId","eventType","occurredAt"}` | 200 sem corpo |

### 3.1 Regras de formato da chave (`PixKey.validate`) e a normalização do `pix_mcp`

| `keyType` | Validação no pix-service | Normalização **[RECOMENDAÇÃO]** no `pix_mcp` |
|---|---|---|
| `CPF` | Após remover não dígitos, 11 dígitos. **DV não validado** | Só dígitos (11) e **validar DV localmente**. A chave `123.456.789-01` e `12345678901` são distintas no servidor |
| `EMAIL` | `^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$` | Minúsculas e mesma regex antes de enviar |
| `PHONE` | Após remover não dígitos, **10 a 11 dígitos**; sem `+55` | **Só DDD + número (10 a 11 dígitos)**. `+55…` teria 12 a 13 dígitos e seria **rejeitado** (correção ao plano original, que previa E.164) |
| `EVP` | Exatamente 36 caracteres | **Gerado** pelo `pix_mcp` (`uuid4`, 36 caracteres) |

A normalização deve ser **idêntica** no registro e na transferência: o `pix-service` compara a string exata (`pixKey` sem normalização, A6).

## 4. Lacunas do contrato e como o MD Bank AI as absorve

| # | Lacuna ([FATO]) | Evidência | Como o `pix_mcp` absorve | Dependência externa |
|---|---|---|---|---|
| L1 | Não existe `GET` de transferência. A6 só devolve `endToEndId` + `PENDING` | doc 03 §3 | `consultar_transferencia` devolve estado **local** com `"fonte": "local"` | **D1:** `GET /pix/transfers/{endToEndId}` |
| L2 | Depósito e saque sem `Idempotency-Key`; resposta sem id de operação | doc 03 §2, A3/A4 | **Sem retry** em POST financeiro. Timeout ⇒ `DESCONHECIDA` e orientar a conferir o saldo | **D2:** idempotência em depósito/saque |
| L3 | Chave de idempotência repetida devolve **409 `Duplicate request`**, **não** a resposta original (D-06). A resposta original (com `endToEndId`) fica só no banco | doc 03 A6, R-06 | `Idempotency-Key = intent_id`. Se o 409 de duplicidade vier num reenvio, a transferência **foi criada**, mas o `endToEndId` **não é recuperável** ⇒ estado `ENVIADA_SEM_E2E` | **D5:** replay da resposta original (R-06 do doc 03) |
| L4 | Sem autenticação nem titularidade; `fromWalletId` vem do corpo; sem busca de carteira por usuário | doc 03 §2, AC-02 | `pix_mcp` guarda `cpf → walletId`; `userId` = hash do CPF (sem PII) | **D3** |
| L5 | Sem limites; chave sem normalização e sem DV do CPF; EVP vem do cliente | doc 03 A2, AC-14 | Seção 3.1 e limites por operação no `pix_mcp` | — |
| L6 | Webhook público | AC-03 | Nunca exposto ao agente | **D3** |
| L7 | Erros de entrada do framework (header ausente, JSON malformado, enum inválido, tipo errado) respondem **500**, não 4xx (D-07, D-08) | doc 03 §6 | O `pix_mcp` sempre envia header e corpo válidos. **500 não é sinal de "falha segura"**: pode ser bug nosso, deadlock (AC-08) ou rollback ⇒ tratar como `desconhecida` | R-01 do doc 03 |
| L8 | Códigos inconsistentes: depósito em carteira inexistente dá **400** `Bad Request` (D-01) | doc 03 A3 | Classificação por `error` + prefixo de `message` (seção 5) | — |
| L9 | PII (chave Pix) em `message`, log e ledger do pix-service | AC-07, R-08 | Não repassar `message`; máscara da Fase 1 em tudo que logamos | Correção no pix-service |
| L10 | `at` pode descartar o offset silenciosamente (**[HIPÓTESE]**) | doc 03 A5, R-09 | Enviar `at` sem offset; fuso do servidor desconhecido | R-09 |
| L11 | Chave Pix é única **globalmente**: 409 em A2 não diz se a chave é desta ou de outra carteira | doc 03 A2 | Mensagem neutra: "chave já registrada" | — |

## 5. Classificação de erros (pix-service → retorno da tool)

**[RECOMENDAÇÃO]** As tools não lançam exceção ao LLM; seguem o padrão de `recursos`: `{"status": "...", "mensagem": "..."}`. Prefixos de `message` conforme o doc 03.

| Endpoint | HTTP / `error` | Prefixo de `message` | `status` da tool |
|---|---|---|---|
| A2 | 404 Not Found | `Wallet not found` | `carteira_inexistente` (inconsistência interna: o vínculo local aponta para carteira que não existe) |
| A2 | 409 Conflict | `Pix key already registered` | `chave_ja_registrada` |
| A2 | 400 Bad Request | `Invalid … format` | `chave_invalida` |
| A3 | 400 **Bad Request** | `Wallet not found` | `carteira_inexistente` |
| A3 / A4 | 400 Validation Failed | `Amount …` | `valor_invalido` |
| A4 | 404 Not Found | `Wallet not found` | `carteira_inexistente` |
| A4 | 409 Conflict | `Insufficient balance. Current: …, Requested: …` | `saldo_insuficiente` (a mensagem do servidor traz o saldo; usamos o nosso texto) |
| A5 | 404 Not Found | `Wallet not found` | `carteira_inexistente` |
| A6 | 404 Not Found | `Pix key not found` | `chave_nao_encontrada` |
| A6 | 404 Not Found | `Source wallet not found` | `carteira_inexistente` |
| A6 | 400 Bad Request | `Cannot transfer to the same wallet` | `mesma_carteira` |
| A6 | 409 Conflict | `Insufficient balance` | `saldo_insuficiente` |
| A6 | 409 Conflict | `Duplicate request` / `Duplicate request detected` | `ja_enviada` (só com o mesmo `intent_id`; ver L3) |
| A6 | 400 Validation Failed | campo obrigatório / `amount` | `valor_invalido` |
| Qualquer POST | timeout, 5xx | — | `desconhecida` (sem retry em A3/A4; reenvio seguro em A6) |
| Qualquer GET | timeout, 5xx | — | `indisponivel` (retry com backoff) |
| Qualquer | `status`/`error`/`message` fora da tabela | — | `erro_desconhecido` (loga `http_status`, **sem** `message` em claro) |

**Ordem de checagem em A6 ([FATO], doc 03):** idempotência → chave → mesma carteira → origem → saldo → destino. Consequência: um reenvio com chave de idempotência já usada **e** chave Pix inexistente responde **409**, não 404.

## 6. Validações pendentes (dependem de execução do pix-service)

Resolvido pelo doc 03: corpo dos erros, nomes dos campos dos DTOs, porta (`8089`), regras de formato da chave. **Ainda pendente**, bloqueando só o teste ponta a ponta:

1. **Build (AC-01 / D4):** o `pix-service` não compila no commit analisado; sem corrigi-lo não há como executar nada abaixo.
2. D-07/D-08: confirmar por execução que header ausente, JSON malformado e enum inválido dão 500 (o `pix_mcp` evita todos, então é informativo).
3. Tamanho da coluna `wallets.user_id` (o `userId` do `pix_mcp` tem prefixo `mdb-` + 32 hex = 36 caracteres; confirmar que cabe).
4. Offset em `at` (L10) e o fuso do servidor.
5. Corrida de `Idempotency-Key` ⇒ 409 `Duplicate request detected` (hoje **[HIPÓTESE]**).

Os testes unitários do `pix_mcp` usam transporte HTTP simulado (`httpx.MockTransport`) com os corpos de erro desta seção e **não** dependem do `pix-service` executável.

## 7. Dependências externas

| ID | Pedido ao pix-service | Impacto se não atendido |
|---|---|---|
| D1 | `GET /pix/transfers/{endToEndId}` (status e timestamps) | "Acompanhar status" fica degradado (estado local, sem confirmação de liquidação) |
| D2 | `Idempotency-Key` em depósito e saque (e id da operação na resposta) | Timeout exige conferir o saldo manualmente, sem reenvio automático |
| D3 | Autenticação entre serviços e assinatura no webhook (R-04) | Qualquer processo na rede chama o `pix-service`. Aceito só em PoC |
| D4 | Corrigir o build (AC-01 / R-12) | Sem `pix-service` executável não há teste ponta a ponta |
| D5 | Replay da resposta original em idempotência repetida (R-06) | Timeout com commit no servidor perde o `endToEndId` (estado `ENVIADA_SEM_E2E`) |
| D6 | Código de erro estável no `ErrorResponse` (R-07) e 400/405/415 no lugar de 500 (R-01) | Classificação por texto livre, frágil a mudança de mensagem |

## 8. Riscos aceitos nesta PoC (bloqueantes para produção)

| ID | Risco | Mitigação parcial |
|---|---|---|
| R1 | O cliente é identificado só pelo CPF digitado no chat. Não há autenticação no MD Bank AI nem no `pix-service` ([arquitetura.md](arquitetura.md), ponto 6; AC-02). Quem souber o CPF opera a carteira | Confirmação em turno separado, limites por operação, trilha de auditoria por `correlation_id` |
| R2 | CPF em texto claro no `pix_db.json` (mesmo padrão do `db.json`) | Fora do log e do Langfuse (máscara) |
| R3 | `InMemorySaver` e `InMemoryTaskStore` perdem estado no restart. Intents persistem no `pix_db.json` | Intent expira em 5 min |
| R4 | `abrir_conta` e `cartao_credito` ainda usam `thread_id="1"` (memória compartilhada entre clientes). O agente de pagamentos **não** herda isso | Corrigir os outros dois é follow-up recomendado |
| R5 | `/chat` executa agentes em paralelo e `/` em sequência ([arquitetura.md](arquitetura.md), ponto 3) | Regra do roteador: operação financeira nunca junto de `abrir_conta` no mesmo turno; e a tool valida a conta |
| R6 | A classificação de erros depende de texto livre de `message` (L7, D6) | Isolada em `client.py` com testes por mensagem; `erro_desconhecido` como fallback seguro |

## 9. Privacidade implementada (Fase 1)

A regra única é `mask()` em `correlation.py`; o Langfuse delega para ela (`observability._mask`). Mascara **CPF, e-mail, telefone BR e EVP** em logs e traces. Notas, todas cobertas por teste em `supervisor/tests/test_correlation.py`:

- Valores de chaves de ID (`correlation_id`, `conversation_id`, `intent_id`, `end_to_end_id` etc.) passam intactos. **Motivo [FATO]:** os IDs de correlação são `uuid4` hifenizado (`new_id`), o mesmo formato do EVP; sem essa lista, os metadados do Langfuse perderiam o ID.
- Um UUID hifenizado em **texto livre** é mascarado como EVP, mesmo que seja um ID de correlação.
- `endToEndId` (`E` + hex) e `intent_id` (`ix_` + hex) não casam com nenhuma regra.
- Sequências com mais de 11 dígitos e a parte inteira de valores decimais não são tratadas como telefone.
- **Limite conhecido:** nomes e endereços continuam sem máscara ([arquitetura.md](arquitetura.md#privacidade)). Um número de 10 dígitos qualquer em texto livre é mascarado como telefone (falso positivo aceito).

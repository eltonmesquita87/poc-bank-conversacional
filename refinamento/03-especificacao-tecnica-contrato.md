# 06 — Especificação técnica do contrato de APIs

> **Escopo:** contrato HTTP do `pix-service` no commit base `698ff49`, branch `main`. Cobre as APIs de entrada (endpoints expostos), as saídas observáveis (respostas, envelope de erro, efeitos persistidos, logs e observabilidade) e a comparação com a documentação Swagger e o README.
> **Método:** leitura estática dos controllers e das interfaces `*ControllerApi`, DTOs, `GlobalExceptionHandler`, casos de uso, entidades, `application.yml`, `nginx/nginx.conf` e da suíte de testes. Cada linha citada foi conferida com `grep -n`. **Nenhuma requisição foi executada.** O build está quebrado (AC-01 em [01-arquitetura-atual.md](01-arquitetura-atual.md)) e o Maven não está instalado no ambiente. Por isso, os pontos marcados como **[HIPÓTESE]** ou **[REF. EXTERNA]** dependem de confirmação por execução (§8).
> **Relação com a análise anterior:** os endpoints A1–A7 e as funcionalidades F1–F12 seguem a numeração de [01-arquitetura-atual.md](01-arquitetura-atual.md). Riscos de segurança e de arquitetura aparecem apenas pelo ID (AC-xx).

## Legenda de evidências

| Marcador | Significado |
|---|---|
| **[FATO]** | Verificado diretamente no código, configuração ou testes, com evidência (arquivo e linha). |
| **[HIPÓTESE]** | Inferência técnica a partir do código, **não** verificada por execução. |
| **[REF. EXTERNA]** | Comportamento do Spring, do PostgreSQL ou do Jackson, baseado em conhecimento externo ao repositório. |
| **[RECOMENDAÇÃO]** | Proposta de mudança no contrato. |

---

## 1. Resumo

- **[FATO]** O serviço expõe **7 endpoints de negócio**: 5 sob `/wallets` e 2 sob `/pix`. Há também endpoints operacionais do Actuator e do Swagger (§3).
- **[FATO]** **Não existem APIs de saída.** Não há cliente HTTP (`RestTemplate`, `WebClient`, Feign), produtor de mensagens nem `@Scheduled` em `src/main`. A liquidação é externa: o provedor a informa pelo webhook `POST /pix/webhook`. A "saída" do contrato é formada pelas respostas síncronas, pelo envelope de erro e pelos efeitos persistidos (§7).
- **[FATO]** O contrato não tem autenticação (AC-02), nem versão no path, nem paginação, nem cabeçalho `Location` nos `201`.
- **[FATO]** A documentação Swagger diverge do comportamento efetivo em **5 respostas** (D-01 a D-05). O README diverge em 1 (D-06), e a porta documentada também difere (D-10).
- **[FATO pelo código; execução pendente]** Erros de entrada tratados pelo framework (header obrigatório ausente, corpo ausente ou malformado, enum inválido, tipo errado em path ou query e método HTTP não suportado) **não são mapeados para 4xx**. Caem no handler genérico, que responde **500** (D-07 e D-08). Os testes desabilitados esperam 400 para o caso do header.

---

## 2. Convenções do contrato

| Aspecto | Contrato efetivo | Evidência |
|---|---|---|
| Porta | `8089` na aplicação. Swagger e README citam `8080` (D-10). | [application.yml#L42](../../src/main/resources/application.yml#L42) |
| Base path | `/wallets` e `/pix`, sem prefixo de versão. | [WalletController.java#L25](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/WalletController.java#L25), [PixController.java#L25](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/PixController.java#L25) |
| Formato | JSON (`application/json`). Não há outro formato. | Controllers |
| Datas | `LocalDateTime` em ISO-8601 sem fuso, por exemplo `2025-10-15T10:00:00`. A fração de segundos pode aparecer. `application.yml` não tem configuração de Jackson, então valem os padrões do Spring Boot. | [application.yml](../../src/main/resources/application.yml) (ausência de `jackson`) |
| Valores monetários | Número JSON com 2 casas (`150.00`). Entrada arredondada em `HALF_UP` (RN-01). Mínimo `0.01` no DTO. Sem teto. | [Money.java#L20](../../src/main/java/com/elton/pixservice/domain/valueobject/Money.java#L20), [DepositRequest.java#L15-L16](../../src/main/java/com/elton/pixservice/infrastructure/web/dto/DepositRequest.java#L15-L16) |
| IDs de carteira | `Long` numérico gerado pelo banco (`BIGSERIAL`). | [V1__create_tables.sql#L2](../../src/main/resources/db/migration/V1__create_tables.sql#L2) |
| `endToEndId` | `"E"` seguido de 32 caracteres hexadecimais, sem hífens (RN-18). | [TransferPixUseCase.java#L70](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L70) |
| Enumerações | Serializadas pelo nome. `keyType`: `CPF`, `EMAIL`, `PHONE`, `EVP`. `status`: `PENDING`, `CONFIRMED`, `REJECTED`. | [PixKeyType.java](../../src/main/java/com/elton/pixservice/domain/valueobject/PixKeyType.java), [TransferStatus.java](../../src/main/java/com/elton/pixservice/domain/valueobject/TransferStatus.java) |
| `eventType` do webhook | Texto livre no DTO. Só `CONFIRMED` e `REJECTED` são aceitos; qualquer outro valor vira 400. | [ProcessWebhookUseCase.java#L40-L49](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L40-L49) |
| Idempotência | Só em `POST /pix/transfers`, pelo header `Idempotency-Key`. Os demais `POST` não são idempotentes: repetir um depósito credita de novo. | [TransferPixUseCase.java#L39-L44](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L39-L44) |
| Autenticação | Nenhuma, em nenhum endpoint, inclusive no webhook (AC-02, AC-03). | Ausência de Spring Security no [pom.xml](../../pom.xml) |
| Paginação e filtros | Não há. A única consulta com parâmetro é `at` em `GET /wallets/{id}/balance`. | Controllers |
| Cabeçalhos de resposta | Sem `Location` no `201`, sem `ETag`. | Controllers (ausência) |

### 2.1 Envelope de erro

Todo erro tratado pelo `GlobalExceptionHandler` tem o mesmo corpo `ErrorResponse` ([ErrorResponse.java](../../src/main/java/com/elton/pixservice/infrastructure/exception/ErrorResponse.java)):

```json
{
  "timestamp": "2025-10-15T10:00:00.123",
  "status": 404,
  "error": "Not Found",
  "message": "Wallet not found: 999",
  "path": "/wallets/999/deposit"
}
```

| Campo | Tipo | Origem | Observação |
|---|---|---|---|
| `timestamp` | `LocalDateTime` | `LocalDateTime.now()` no momento do erro | Hora do servidor, sem fuso. |
| `status` | `int` | Código HTTP da resposta | Igual ao status da resposta. |
| `error` | `string` | Rótulo fixo por handler | Um de: `Bad Request`, `Not Found`, `Conflict`, `Validation Failed`, `Internal Server Error`. |
| `message` | `string` | `ex.getMessage()` ou texto fixo | Texto livre. Pode conter a chave Pix (ex.: `Pix key not found: x@y.com`). |
| `path` | `string` | `request.getRequestURI()` | Sem query string. |

**[FATO]** Não há código de erro estável. Um cliente que precisa distinguir dois 409 (ex.: saldo insuficiente e chave duplicada) só pode comparar o texto de `message` (R-07).

### 2.2 Mapeamento de exceções para HTTP

**[FATO]** O mapeamento fica centralizado em [GlobalExceptionHandler.java](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java).

| Exceção | HTTP | `error` | Lançada em | Handler |
|---|---|---|---|---|
| `WalletNaoEncontradaException` | 404 | Not Found | [GetBalanceUseCase.java#L31](../../src/main/java/com/elton/pixservice/usecase/GetBalanceUseCase.java#L31), [RegisterPixKeyUseCase.java#L28](../../src/main/java/com/elton/pixservice/usecase/RegisterPixKeyUseCase.java#L28), [WithdrawUseCase.java#L28](../../src/main/java/com/elton/pixservice/usecase/WithdrawUseCase.java#L28), [TransferPixUseCase.java#L48](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L48) | [L27](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L27) |
| `SaldoInsuficienteException` | 409 | Conflict | [Wallet.java#L44](../../src/main/java/com/elton/pixservice/domain/entity/Wallet.java#L44), [TransferPixUseCase.java#L61](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L61) | [L45](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L45) |
| `ChavePixJaRegistradaException` | 409 | Conflict | [RegisterPixKeyUseCase.java#L33](../../src/main/java/com/elton/pixservice/usecase/RegisterPixKeyUseCase.java#L33) | [L61](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L61) |
| `RequisicaoDuplicadaException` | 409 | Conflict | [TransferPixUseCase.java#L43](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L43) | [L77](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L77) |
| `ValorInvalidoException` | 400 | Bad Request | [Wallet.java#L34](../../src/main/java/com/elton/pixservice/domain/entity/Wallet.java#L34), [Money.java#L18](../../src/main/java/com/elton/pixservice/domain/valueobject/Money.java#L18) | [L95](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L95) |
| `ChavePixInvalidaException` | 400 | Bad Request | [PixKey.java#L26-L73](../../src/main/java/com/elton/pixservice/domain/entity/PixKey.java#L26-L73) | [L111](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L111) |
| `TransferenciaInvalidaException` | 400 | Bad Request | [TransferPixUseCase.java#L53](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L53), [PixTransfer.java#L32](../../src/main/java/com/elton/pixservice/domain/entity/PixTransfer.java#L32) | [L127](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L127) |
| `TipoEventoDesconhecidoException` | 400 | Bad Request | [ProcessWebhookUseCase.java#L48](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L48) | [L143](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L143) |
| `TipoLancamentoDesconhecidoException` | 500 | Internal Server Error | `LedgerEntry.getSignedAmount`, no `default` do `switch`. Inalcançável com o enum atual. | [L159](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L159) |
| `IllegalArgumentException` | 400 | Bad Request | [DepositUseCase.java#L27](../../src/main/java/com/elton/pixservice/usecase/DepositUseCase.java#L27), [ProcessWebhookUseCase.java#L38](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L38) | [L195](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L195) |
| `IllegalStateException` | 409 | Conflict | Sem origem identificada no código. | [L211](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L211) |
| `MethodArgumentNotValidException` | 400 | Validation Failed | Bean Validation nos DTOs. As mensagens de campo são unidas por `; `. | [L227](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L227) |
| `DataIntegrityViolationException` | 409 | Conflict | Constraint do banco. `uk_pix_key_value` vira `Pix key already registered`; `uk_scope_key` vira `Duplicate request detected`; as demais viram `Data integrity violation`. A tradução depende de busca por substring na mensagem da exceção. | [L247](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L247) |
| `Exception` (qualquer outra) | 500 | Internal Server Error | Inclui as exceções do Spring MVC sem handler próprio (D-07 e D-08). | [L270](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L270) |

---

## 3. Catálogo de endpoints

| ID | Funcionalidade | Método e path | Corpo | Sucesso | Efeito principal |
|---|---|---|---|---|---|
| A1 | F1 — Abrir carteira | `POST /wallets` | `CreateWalletRequest` | 201 `WalletResponse` | Cria carteira com saldo 0,00 |
| A2 | F2 — Registrar chave Pix | `POST /wallets/{id}/pix-keys` | `RegisterPixKeyRequest` | 201 `PixKeyResponse` | Insere em `pix_keys` |
| A3 | F3 — Depositar | `POST /wallets/{id}/deposit` | `DepositRequest` | 200 `WalletResponse` | Credita saldo; lançamento `DEPOSIT` |
| A4 | F4 — Sacar | `POST /wallets/{id}/withdraw` | `WithdrawRequest` | 200 `WalletResponse` | Debita saldo; lançamento `WITHDRAW` |
| A5 | F5 e F6 — Consultar saldo | `GET /wallets/{id}/balance[?at=]` | — | 200 `BalanceResponse` | Leitura. Sem `at`: saldo materializado. Com `at`: soma do ledger |
| A6 | F7 e F10 — Transferir | `POST /pix/transfers` + `Idempotency-Key` | `TransferPixRequest` | 201 `TransferPixResponse` (`PENDING`) | Debita a origem; cria transferência `PENDING`; lançamento `TRANSFER_DEBIT` |
| A7 | F8, F9 e F11 — Webhook | `POST /pix/webhook` | `WebhookRequest` | 200 sem corpo | `CONFIRMED` credita o destino; `REJECTED` estorna a origem |

**Endpoints operacionais** (fora do contrato de negócio):

| Endpoint | Função | Evidência |
|---|---|---|
| `GET /actuator/health`, `/info`, `/metrics`, `/prometheus` | Saúde e métricas | [application.yml#L47-L58](../../src/main/resources/application.yml#L47-L58) |
| `GET /swagger-ui/` e `GET /v2/api-docs` | Documentação interativa e JSON OpenAPI (springfox 3.0.0) | [SwaggerConfig.java#L29-L30](../../src/main/java/com/elton/pixservice/infrastructure/config/SwaggerConfig.java#L29-L30) |
| `GET /health` | Health do balanceador NGINX | [nginx.conf#L120](../../nginx/nginx.conf#L120) |

---

## 4. Especificação por endpoint

### A1 — Criar carteira (F1)

`POST /wallets` · `Content-Type: application/json` · Caso de uso: `CreateWalletUseCase.execute` · [WalletController.java#L36-L50](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/WalletController.java#L36-L50)

**Corpo**

| Campo | Tipo | Obrigatório | Regra | Mensagem de erro |
|---|---|---|---|---|
| `userId` | string | sim | Não nulo, não vazio e não só espaços (`@NotBlank`). | `User ID is required` |

```json
{ "userId": "user123" }
```

**Sucesso: 201**

| Campo | Tipo | Observação |
|---|---|---|
| `id` | number | Gerado pelo banco. |
| `userId` | string | Eco do corpo. |
| `balance` | number | Sempre `0.00` nesta resposta. |

```json
{ "id": 1, "userId": "user123", "balance": 0.00 }
```

**Erros**

| HTTP | `error` | Quando | Exemplo de `message` |
|---|---|---|---|
| 400 | Validation Failed | `userId` ausente, vazio ou só espaços. | `User ID is required` |
| 500 | Internal Server Error | Corpo ausente ou JSON malformado (D-08). | `An unexpected error occurred` |

**Efeitos:** insere em `wallets` com `balance = 0` e `version = 0` (RN-06). Não gera lançamento. Um mesmo `userId` pode ter várias carteiras (F1).

---

### A2 — Registrar chave Pix (F2)

`POST /wallets/{id}/pix-keys` · Caso de uso: `RegisterPixKeyUseCase.execute` · [WalletController.java#L52-L70](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/WalletController.java#L52-L70)

**Path:** `id` (`Long`), carteira dona da chave.

**Corpo**

| Campo | Tipo | Obrigatório | Regra | Mensagem de erro |
|---|---|---|---|---|
| `keyType` | enum | sim | `CPF`, `EMAIL`, `PHONE` ou `EVP`. | `Key type is required` |
| `keyValue` | string | sim | Não vazio. Formato conforme `keyType` (tabela abaixo). | `Key value is required` |

**Formato por `keyType`** (validação em `PixKey.validate`):

| `keyType` | Regra | Erro (`message`) | Evidência |
|---|---|---|---|
| `CPF` | Após remover os não dígitos, 11 dígitos. Os dígitos verificadores **não** são validados (RN-09). | `Invalid CPF format: <valor>` | [PixKey.java#L49-L54](../../src/main/java/com/elton/pixservice/domain/entity/PixKey.java#L49-L54) |
| `EMAIL` | Regex `^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$` (RN-10). | `Invalid email format: <valor>` | [PixKey.java#L56-L60](../../src/main/java/com/elton/pixservice/domain/entity/PixKey.java#L56-L60) |
| `PHONE` | Após remover os não dígitos, 10 a 11 dígitos. Não exige `+55` nem DDD (RN-11). | `Invalid phone format: <valor>` | [PixKey.java#L62-L67](../../src/main/java/com/elton/pixservice/domain/entity/PixKey.java#L62-L67) |
| `EVP` | Exatamente 36 caracteres (RN-12). | `Invalid EVP format: <valor>` | [PixKey.java#L69-L73](../../src/main/java/com/elton/pixservice/domain/entity/PixKey.java#L69-L73) |

```json
{ "keyType": "EMAIL", "keyValue": "user@example.com" }
```

**Sucesso: 201**

```json
{ "id": 10, "walletId": 1, "keyType": "EMAIL", "keyValue": "user@example.com" }
```

**Erros** (a ordem de checagem é: carteira, duplicidade e, por último, formato)

| HTTP | `error` | Quando | Exemplo de `message` |
|---|---|---|---|
| 400 | Validation Failed | `keyType` ou `keyValue` ausente ou vazio. | `Key type is required` |
| 400 | Bad Request | Formato inválido para o tipo informado. | `Invalid email format: abc` |
| 404 | Not Found | Carteira inexistente. Checado antes do formato. | `Wallet not found: 999` |
| 409 | Conflict | `keyValue` já cadastrada em qualquer carteira. Checado antes do formato. | `Pix key already registered: user@example.com` |
| 500 | Internal Server Error | `keyType` fora do enum, como `"CNPJ"` (D-08). | `An unexpected error occurred` |

**Efeitos:** insere em `pix_keys`. Sem lançamento.

**Observações**
- **[FATO]** A chave não é normalizada: `123.456.789-01` e `12345678901` são chaves distintas (AC-14).
- **[FATO]** A chave aparece na resposta, nas mensagens de erro e no log de INFO (`RegisterPixKeyUseCase.java#L24`). Ver R-08.

---

### A3 — Depositar (F3)

`POST /wallets/{id}/deposit` · Caso de uso: `DepositUseCase.execute` · [WalletController.java#L72-L89](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/WalletController.java#L72-L89)

**Path:** `id` (`Long`).

**Corpo**

| Campo | Tipo | Obrigatório | Regra | Mensagem de erro |
|---|---|---|---|---|
| `amount` | decimal | sim | ≥ 0,01 (RN-03). | `Amount is required`; `Amount must be greater than zero` |

```json
{ "amount": 100.00 }
```

**Sucesso: 200**

```json
{ "id": 1, "userId": "user123", "balance": 100.00 }
```

**Erros**

| HTTP | `error` | Quando | Exemplo de `message` |
|---|---|---|---|
| 400 | Validation Failed | `amount` ausente. | `Amount is required` |
| 400 | Validation Failed | `amount` menor que 0,01, inclusive negativo. | `Amount must be greater than zero` |
| 400 | Bad Request | Carteira inexistente. **Divergente:** o Swagger diz 404 (D-01). | `Wallet not found: 999` |
| 500 | Internal Server Error | Corpo malformado ou `amount` não numérico (D-08). | `An unexpected error occurred` |

**Efeitos:** soma em `wallets.balance`. Lançamento `DEPOSIT` com metadata `Deposit operation` (RN-25).

**Observações**
- **[FATO]** A resposta devolve só o saldo. Não há identificador da operação. O lançamento só é visível no banco, pois não há endpoint de extrato.
- **[FATO]** Valores com mais de 2 casas são validados antes do arredondamento. `0.015` passa na validação (≥ 0,01) e é gravado como `0.02` (RN-01).
- **[FATO]** Não há origem de fundos (AC-04).

---

### A4 — Sacar (F4)

`POST /wallets/{id}/withdraw` · Caso de uso: `WithdrawUseCase.execute` · [WalletController.java#L91-L108](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/WalletController.java#L91-L108)

**Path:** `id` (`Long`).

**Corpo**

| Campo | Tipo | Obrigatório | Regra | Mensagem de erro |
|---|---|---|---|---|
| `amount` | decimal | sim | ≥ 0,01 (RN-04). | `Amount is required`; `Amount must be greater than zero` |

```json
{ "amount": 50.00 }
```

**Sucesso: 200**

```json
{ "id": 1, "userId": "user123", "balance": 50.00 }
```

**Erros**

| HTTP | `error` | Quando | Exemplo de `message` |
|---|---|---|---|
| 400 | Validation Failed | `amount` ausente ou menor que 0,01. | `Amount must be greater than zero` |
| 404 | Not Found | Carteira inexistente. | `Wallet not found: 999` |
| 409 | Conflict | Saldo menor que o valor solicitado (RN-05). **Divergente:** o Swagger diz 400 (D-02). | `Insufficient balance. Current: 50.00, Requested: 100.00` |
| 500 | Internal Server Error | Corpo malformado ou `amount` não numérico (D-08). | `An unexpected error occurred` |

**Efeitos:** debita `wallets.balance`. Lançamento `WITHDRAW` com metadata `Withdraw operation`. Não há destino para o saque: é apenas um débito (F4).

---

### A5 — Consultar saldo (F5 e F6)

`GET /wallets/{id}/balance[?at=]` · Casos de uso: `GetBalanceUseCase.getCurrentBalance` (sem `at`) e `GetBalanceUseCase.getHistoricalBalance` (com `at`) · [WalletController.java#L110-L129](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/WalletController.java#L110-L129)

**Parâmetros**

| Nome | Local | Tipo | Obrigatório | Formato |
|---|---|---|---|---|
| `id` | path | `Long` | sim | — |
| `at` | query | `LocalDateTime` | não | ISO-8601 local, `yyyy-MM-ddTHH:mm:ss`. Ver observação de fuso abaixo. |

**Sucesso: 200**

| Campo | Tipo | Observação |
|---|---|---|
| `walletId` | number | Eco do path. |
| `balance` | number | Duas casas decimais. |
| `timestamp` | `LocalDateTime` | `now()` do servidor quando `at` é omitido. Eco de `at` quando informado. |

```json
{ "walletId": 1, "balance": 350.00, "timestamp": "2026-10-24T10:15:30" }
```

Consulta histórica, `GET /wallets/1/balance?at=2025-10-15T10:00:00`:

```json
{ "walletId": 1, "balance": 100.00, "timestamp": "2025-10-15T10:00:00" }
```

**Regras da consulta histórica**
- **[FATO]** O saldo é a soma assinada dos lançamentos com `created_at` **estritamente anterior** a `at` (RN-26, RN-27).
- **[FATO]** `at` no futuro não gera erro: devolve a soma de todos os lançamentos.
- **[FATO]** `at` anterior à criação da carteira não gera erro: devolve `0.00`.

**Erros**

| HTTP | `error` | Quando | Exemplo de `message` |
|---|---|---|---|
| 404 | Not Found | Carteira inexistente. Vale para os dois modos. | `Wallet not found: 999` |
| 500 | Internal Server Error | `at` malformado, como só a data (`2025-10-15`) (D-08). | `An unexpected error occurred` |

**Observação de fuso [HIPÓTESE]:** `@DateTimeFormat(iso = DATE_TIME)` com `LocalDateTime` usa o formatter ISO, que aceita offset, e o offset é descartado na conversão para `LocalDateTime` [REF. EXTERNA]. Se confirmado, `at=2025-10-15T10:00:00-03:00` seria lido como `10:00` no fuso do servidor, sem erro e sem aviso. Isso é um risco de contrato em um serviço brasileiro. Ver R-09.

**Efeitos:** só leitura. O saldo atual lê `wallets.balance` sem lock (F5, [01-arquitetura-atual.md](01-arquitetura-atual.md)). O histórico percorre todos os lançamentos da carteira (F6).

---

### A6 — Realizar transferência Pix (F7 e F10)

`POST /pix/transfers` · Caso de uso: `TransferPixUseCase.execute` · [PixController.java#L33-L57](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/PixController.java#L33-L57)

**Cabeçalho**

| Nome | Tipo | Obrigatório | Regra |
|---|---|---|---|
| `Idempotency-Key` | string | sim | Sem validação de formato ou tamanho na aplicação. A coluna do banco tem `VARCHAR(255)` ([V1#L64](../../src/main/resources/db/migration/V1__create_tables.sql#L64)). Escopo fixo `pix_transfer`. |

**Corpo**

| Campo | Tipo | Obrigatório | Regra | Mensagem de erro |
|---|---|---|---|---|
| `fromWalletId` | `Long` | sim | Carteira de origem. Vem do corpo, sem vínculo com o chamador (AC-02). | `From wallet ID is required` |
| `pixKey` | string | sim | Não vazio. Busca exata pelo valor, sem normalização. | `Pix key is required` |
| `amount` | decimal | sim | ≥ 0,01. | `Amount is required`; `Amount must be greater than zero` |

```http
POST /pix/transfers
Idempotency-Key: unique-key-123
Content-Type: application/json

{ "fromWalletId": 1, "pixKey": "user@example.com", "amount": 150.00 }
```

**Sucesso: 201**

| Campo | Tipo | Observação |
|---|---|---|
| `endToEndId` | string | `E` seguido de 32 hexadecimais. |
| `fromWalletId` | `Long` | Eco do corpo. |
| `toWalletId` | `Long` | Carteira dona da chave Pix. |
| `amount` | number | Duas casas decimais. |
| `status` | enum | Sempre `PENDING` nesta resposta. |

```json
{
  "endToEndId": "E9b1d2c3e4f5a6b7c8d9e0f1a2b3c4d5e",
  "fromWalletId": 1,
  "toWalletId": 2,
  "amount": 150.00,
  "status": "PENDING"
}
```

**Ordem de checagem no caso de uso** (a primeira falha vence):

1. `Idempotency-Key` já usada → 409 ([TransferPixUseCase.java#L40-L43](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L40-L43)).
2. Chave Pix cadastrada → 404 ([L47-L48](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L47-L48)).
3. Origem diferente do destino → 400 ([L52-L53](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L52-L53)).
4. Carteira de origem existente → 404 ([L57-L58](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L57-L58)).
5. Saldo da origem suficiente → 409 ([L60-L61](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L60-L61)).
6. Carteira de destino existente → 404 ([L65-L66](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L65-L66)).

**Consequência para o cliente:** um retry com chave já usada e chave Pix inexistente devolve **409**, não 404.

**Erros**

| HTTP | `error` | Quando | Exemplo de `message` |
|---|---|---|---|
| 400 | Validation Failed | Campo obrigatório ausente, `pixKey` vazio ou `amount` menor que 0,01. | `From wallet ID is required` |
| 400 | Bad Request | Origem e destino são a mesma carteira. | `Cannot transfer to the same wallet` |
| 404 | Not Found | Chave Pix não cadastrada. **Divergente:** Swagger e teste dizem 400 (D-03). | `Pix key not found: nonexistent@example.com` |
| 404 | Not Found | Carteira de origem inexistente. | `Source wallet not found: 999` |
| 409 | Conflict | Saldo insuficiente. | `Insufficient balance` |
| 409 | Conflict | `Idempotency-Key` já usada, mesmo com corpo diferente. **Não** devolve a resposta original (D-06). | `Duplicate request` |
| 409 | Conflict | Duas requisições simultâneas com a mesma chave. A segunda falha na `uk_scope_key` [HIPÓTESE]. | `Duplicate request detected` |
| 500 | Internal Server Error | Header `Idempotency-Key` ausente. O teste e o Swagger esperam 400 (D-07). | `An unexpected error occurred` |
| 500 | Internal Server Error | Corpo malformado ou tipo inválido (D-08). | `An unexpected error occurred` |

**Efeitos** (mesma transação):
- `wallets` (origem): debitada imediatamente.
- `pix_transfers`: nova linha com `status = PENDING`.
- `ledger_entries`: `TRANSFER_DEBIT` com `end_to_end_id` e metadata `Pix transfer to <pixKey>`. A chave Pix fica em texto claro (AC-07).
- `idempotency_keys`: `scope = pix_transfer`, `key_value = <Idempotency-Key>`, `response = <endToEndId>`.
- **[FATO]** O destino **não** é creditado aqui. O crédito acontece só no webhook `CONFIRMED` (A7).

**Observações**
- **[FATO]** A chave de idempotência não é ligada ao payload. A mesma chave com outro corpo também devolve 409 (F10).
- **[FATO]** O `201` não traz `Location`.

---

### A7 — Processar webhook de liquidação (F8, F9 e F11)

`POST /pix/webhook` · Caso de uso: `ProcessWebhookUseCase.execute` · [PixController.java#L59-L71](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/PixController.java#L59-L71)

**Corpo**

| Campo | Tipo | Obrigatório | Regra | Mensagem de erro |
|---|---|---|---|---|
| `endToEndId` | string | sim | Não vazio. Identifica a transferência. | `End to end ID is required` |
| `eventId` | string | sim | Não vazio. Chave de deduplicação (`uk_event_id`). | `Event ID is required` |
| `eventType` | string | sim | Não vazio no DTO. No caso de uso, só `CONFIRMED` e `REJECTED`. | `Event type is required` |
| `occurredAt` | `LocalDateTime` | sim | Obrigatório, mas **ignorado** pelo caso de uso (D-09). | `Occurred at is required` |

```json
{
  "endToEndId": "E9b1d2c3e4f5a6b7c8d9e0f1a2b3c4d5e",
  "eventId": "evt_abc123",
  "eventType": "CONFIRMED",
  "occurredAt": "2025-10-13T10:30:00"
}
```

**Sucesso: 200**, com corpo vazio.

**Comportamento por condição** (ordem de avaliação no caso de uso):

| # | Condição | HTTP | Efeito | Evidência |
|---|---|---|---|---|
| 1 | `eventId` já processado. Vale mesmo se `eventType` ou `endToEndId` forem diferentes do original. | 200 | Nenhum. | [ProcessWebhookUseCase.java#L31-L34](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L31-L34) |
| 2 | `endToEndId` não existe. Mensagem `Transfer not found: E…`. **Divergente:** Swagger diz 404 (D-04). | 400 | Rollback. O evento não é gravado. | [L37-L38](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L37-L38) |
| 3 | `eventType` diferente de `CONFIRMED` e `REJECTED`. Checado depois da busca da transferência. | 400 | Rollback. Mensagem `Unknown event type: X`. | [L40-L48](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L40-L48) |
| 4 | `CONFIRMED` em transferência `PENDING`. | 200 | Status vira `CONFIRMED`. Crédito no destino. Lançamento `TRANSFER_CREDIT`. Evento gravado. | [L57-L85](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L57-L85) |
| 5 | `REJECTED` em transferência `PENDING`. | 200 | Status vira `REJECTED`. Estorno na origem. Lançamento `DEPOSIT` com metadata `Pix transfer rejected - refund`. Evento gravado. | [L87-L115](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L87-L115) |
| 6 | Transição inválida: `REJECTED` depois de `CONFIRMED`, ou novo `CONFIRMED` com outro `eventId`. **Divergente:** Swagger diz 400 (D-05). | 200 | Sem efeito no saldo. O evento **é gravado** como processado (RN-23). | [L58-L62](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L58-L62), [L88-L92](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L88-L92), [L52](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L52) |

**Erros de validação:** 400 `Validation Failed`, com as mensagens separadas por `; `.

**Erros inesperados:** 500 para `occurredAt` malformado ou JSON malformado (D-08).

**Efeitos:** tudo na mesma transação (`@Transactional`) com `webhook_events`, `pix_transfers`, `wallets` e `ledger_entries`. Qualquer exceção desfaz tudo, inclusive a gravação de `webhook_events`. Por isso o reenvio do provedor reprocessa o evento.

**Observações**
- **[FATO]** Não há autenticação nem assinatura (AC-03). Qualquer chamador pode confirmar ou rejeitar uma transferência.
- **[FATO]** O repositório não define a semântica de retentativa do provedor: quais códigos disparam reenvio. Por isso, o efeito de um 400 em `Transfer not found` depende do provedor.

---

## 5. Matriz de rastreabilidade

| Funcionalidade | Endpoint | Entrada (DTO) | Saída (DTO) | Caso de uso | Tabelas escritas | Lançamento no ledger | Testes (estado) |
|---|---|---|---|---|---|---|---|
| F1 Abrir carteira | A1 | `CreateWalletRequest` | `WalletResponse` | `CreateWalletUseCase` | `wallets` | — | `CreateWalletUseCaseTest` (não compila, AC-01); suíte REST `@Disabled` |
| F2 Registrar chave Pix | A2 | `RegisterPixKeyRequest` | `PixKeyResponse` | `RegisterPixKeyUseCase` | `pix_keys` | — | Suíte REST `@Disabled`; sem teste unitário |
| F3 Depositar | A3 | `DepositRequest` | `WalletResponse` | `DepositUseCase` | `wallets`, `ledger_entries` | `DEPOSIT` | Suíte REST `@Disabled`; sem teste unitário |
| F4 Sacar | A4 | `WithdrawRequest` | `WalletResponse` | `WithdrawUseCase` | `wallets`, `ledger_entries` | `WITHDRAW` | `WithdrawUseCaseTest` (não compila, AC-01) |
| F5 Saldo atual | A5 | — | `BalanceResponse` | `GetBalanceUseCase.getCurrentBalance` | — (leitura de `wallets`) | — | Suíte REST `@Disabled`; sem teste unitário |
| F6 Saldo histórico | A5 (`at`) | — | `BalanceResponse` | `GetBalanceUseCase.getHistoricalBalance` | — (leitura de `ledger_entries`) | — | Suíte REST `@Disabled`; sem teste unitário |
| F7 Iniciar transferência | A6 | `TransferPixRequest` | `TransferPixResponse` | `TransferPixUseCase` | `pix_transfers`, `wallets`, `ledger_entries`, `idempotency_keys` | `TRANSFER_DEBIT` | `TransferPixUseCaseTest` (não compila); `PixControllerRestAssuredTest` `@Disabled` |
| F8 Confirmar liquidação | A7 | `WebhookRequest` | 200 sem corpo | `ProcessWebhookUseCase.processConfirmation` | `webhook_events`, `pix_transfers`, `wallets`, `ledger_entries` | `TRANSFER_CREDIT` | `ProcessWebhookUseCaseTest` (não compila) |
| F9 Rejeitar e estornar | A7 | `WebhookRequest` | 200 sem corpo | `ProcessWebhookUseCase.processRejection` | `webhook_events`, `pix_transfers`, `wallets`, `ledger_entries` | `DEPOSIT` (refund) | `ProcessWebhookUseCaseTest` (não compila) |
| F10 Idempotência | A6 (header) | `Idempotency-Key` | 409 em duplicidade | `IdempotencyRepository` | `idempotency_keys` | — | `TransferPixUseCaseTest` (não compila) |
| F11 Deduplicação de webhook | A7 (`eventId`) | `eventId` | 200 em duplicidade | `WebhookEventRepository` | `webhook_events` | — | `ProcessWebhookUseCaseTest` (não compila) |
| F12 Auditoria | — | — | — | SQL manual em [USEFUL_QUERIES.sql](../../uteis/USEFUL_QUERIES.sql) | — | — | Sem endpoint |

**[FATO]** Nenhum teste ativo exercita o contrato HTTP. Todas as suítes REST estão `@Disabled`, e as unitárias não compilam (AC-01, [01-arquitetura-atual.md §13](01-arquitetura-atual.md)).

---

## 6. Divergências entre contrato documentado e comportamento efetivo

| ID | Endpoint | Condição | Documentado | Efetivo | Evidência | Estado |
|---|---|---|---|---|---|---|
| D-01 | A3 `POST /wallets/{id}/deposit` | Carteira inexistente | 404 (Swagger) | 400 | [DepositUseCase.java#L27](../../src/main/java/com/elton/pixservice/usecase/DepositUseCase.java#L27), [GlobalExceptionHandler.java#L195](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L195) | AC-10 |
| D-02 | A4 `POST /wallets/{id}/withdraw` | Saldo insuficiente | 400, "Valor inválido ou saldo insuficiente" (Swagger) | 409 | [Wallet.java#L44](../../src/main/java/com/elton/pixservice/domain/entity/Wallet.java#L44), [GlobalExceptionHandler.java#L45](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L45) | Novo |
| D-03 | A6 `POST /pix/transfers` | Chave Pix inexistente | 400 (Swagger) e 400 (teste [PixControllerRestAssuredTest.java#L166](../../src/test/java/com/elton/pixservice/infrastructure/web/controller/PixControllerRestAssuredTest.java#L166)) | 404 | [TransferPixUseCase.java#L48](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L48) | AC-10 |
| D-04 | A7 `POST /pix/webhook` | Transferência inexistente | 404 (Swagger) | 400 | [ProcessWebhookUseCase.java#L38](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L38) | AC-10 |
| D-05 | A7 `POST /pix/webhook` | Transição inválida | 400 (Swagger) | 200, sem efeito | [ProcessWebhookUseCase.java#L58-L62](../../src/main/java/com/elton/pixservice/usecase/ProcessWebhookUseCase.java#L58-L62) | Novo (ligado a AC-06 e RN-23) |
| D-06 | A6 `POST /pix/transfers` | Chave de idempotência repetida | README: reproduz a resposta original ([README.md#L533](../../README.md#L533)) | 409 `Duplicate request` | [TransferPixUseCase.java#L40-L43](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L40-L43) | AC-09 |
| D-07 | A6 `POST /pix/transfers` | Header `Idempotency-Key` ausente | 400 (teste [PixControllerRestAssuredTest.java#L98](../../src/test/java/com/elton/pixservice/infrastructure/web/controller/PixControllerRestAssuredTest.java#L98), desabilitado) | 500 [HIPÓTESE] | [GlobalExceptionHandler.java#L270](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L270) | Novo |
| D-08 | Todos os endpoints com corpo, path ou query | Corpo ausente ou malformado, enum inválido (`keyType`), tipo errado (`id`, `amount`, `at`), método HTTP não suportado | Não documentado como 400 | 500 [REF. EXTERNA] | [GlobalExceptionHandler.java#L270](../../src/main/java/com/elton/pixservice/infrastructure/exception/GlobalExceptionHandler.java#L270) | Novo |
| D-09 | A7 `POST /pix/webhook` | `occurredAt` | Obrigatório no DTO e no exemplo do README | Lido, validado e descartado | [PixController.java#L61-L70](../../src/main/java/com/elton/pixservice/infrastructure/web/controller/PixController.java#L61-L70), [WebhookRequest.java#L24-L25](../../src/main/java/com/elton/pixservice/infrastructure/web/dto/WebhookRequest.java#L24-L25) | Novo (ligado a F8 em 01) |
| D-10 | Toda a API | Porta | 8080 (Swagger e README) | 8089 | [application.yml#L42](../../src/main/resources/application.yml#L42), [SwaggerConfig.java#L29](../../src/main/java/com/elton/pixservice/infrastructure/config/SwaggerConfig.java#L29) | AC-11 |

**Causa comum de D-07 e D-08.** O `@ExceptionHandler(Exception.class)` do `GlobalExceptionHandler` captura as exceções do Spring MVC que não têm handler próprio, como `HttpMessageNotReadableException`, `MissingRequestHeaderException`, `MethodArgumentTypeMismatchException`, `HttpRequestMethodNotSupportedException` e `HttpMediaTypeNotSupportedException`. O resolver de `@ControllerAdvice` roda antes do resolver padrão do Spring, que é o único que daria 400 ou 405 [REF. EXTERNA]. Por isso, as respostas viram 500.

---

## 7. Saídas não-HTTP e observabilidade

| Saída | Conteúdo | Evidência |
|---|---|---|
| Banco PostgreSQL | 6 tabelas: `wallets`, `pix_keys`, `ledger_entries`, `pix_transfers`, `idempotency_keys`, `webhook_events`. | [V1__create_tables.sql](../../src/main/resources/db/migration/V1__create_tables.sql) |
| Logs | Nível INFO com IDs, valores e chaves Pix. Pelo menos `keyValue` ([RegisterPixKeyUseCase.java#L24](../../src/main/java/com/elton/pixservice/usecase/RegisterPixKeyUseCase.java#L24)) e `pixKey` ([TransferPixUseCase.java#L35](../../src/main/java/com/elton/pixservice/usecase/TransferPixUseCase.java#L35)) aparecem em texto claro (AC-07). | Use cases |
| Eventos e mensageria | **Nenhum.** Não há publicação para terceiros. | §1 |
| Actuator | `health` (com detalhes), `info`, `metrics` e `prometheus`. | [application.yml#L47-L58](../../src/main/resources/application.yml#L47-L58) |
| NGINX, porta 80 | `/health` fixo; `/actuator/health` agregado; `location /` repassa **todo o resto**, incluindo `/actuator/metrics` e `/actuator/prometheus`. Os cabeçalhos `X-Upstream-Addr` e `X-Response-Time` vão a todos os clientes. | [nginx.conf#L107-L173](../../nginx/nginx.conf#L107-L173) |
| NGINX, porta 8081 | `location /actuator` sem restrição de rede ou autenticação no arquivo. | [nginx.conf#L178-L201](../../nginx/nginx.conf#L178-L201) |
| Swagger | `/swagger-ui/` e `/v2/api-docs`, sem restrição de acesso no código. | [SwaggerConfig.java#L29-L30](../../src/main/java/com/elton/pixservice/infrastructure/config/SwaggerConfig.java#L29-L30) |

---

## 8. Verificação e limites

**O que foi verificado:** leitura de todos os arquivos do escopo. Cada linha citada foi conferida com `grep -n`.

**O que não foi verificado:** nenhuma requisição foi executada. Dois motivos:
1. **Build quebrado (AC-01).** `IdempotencyRepositoryImpl.findResponse` está anotado com `@Override`, mas a porta `IdempotencyRepository` não declara o método ([IdempotencyRepositoryImpl.java#L28-L33](../../src/main/java/com/elton/pixservice/infrastructure/persistence/repository/IdempotencyRepositoryImpl.java#L28-L33), [IdempotencyRepository.java](../../src/main/java/com/elton/pixservice/domain/repository/IdempotencyRepository.java)).
2. **Ferramental.** O Java 21 está instalado, mas `mvn` não está.

**Itens que dependem de execução:**
1. D-07: header `Idempotency-Key` ausente responde 500, não 400.
2. D-08: corpo malformado, enum inválido, tipo errado e método não suportado respondem 500.
3. Validação pela anotação `@Valid` declarada só na interface `*ControllerApi`. [HIPÓTESE] O Spring MVC 5.1 ou superior lê anotações de parâmetros de interface, então a validação deve funcionar.
4. Offset em `at` é descartado (A5).
5. Corrida na `Idempotency-Key` resulta em 409 `Duplicate request detected` (A6).

**Plano sugerido:**
1. Corrigir o AC-01.
2. Reativar `PixControllerRestAssuredTest` e `WalletControllerRestAssuredTest`, hoje `@Disabled`.
3. Acrescentar casos para D-07, D-08 e para `at` com offset.
4. Comparar o `/v2/api-docs` gerado com esta especificação.

---

## 9. Recomendações

| ID | Recomendação | Resolve | Prioridade |
|---|---|---|---|
| R-01 | **[RECOMENDAÇÃO]** Mapear explicitamente as exceções do Spring MVC: `HttpMessageNotReadableException`, `MissingRequestHeaderException` e `MethodArgumentTypeMismatchException` para 400; `HttpRequestMethodNotSupportedException` para 405; `HttpMediaTypeNotSupportedException` para 415. Deixar o `Exception` genérico como último recurso. | D-07, D-08 | Alta |
| R-02 | **[RECOMENDAÇÃO]** Escolher uma única fonte de verdade para os códigos. Proposta: 404 para recurso inexistente (D-01, D-03, D-04) e 409 para saldo insuficiente (D-02), que já é o esperado pelo teste de transferência ([PixControllerRestAssuredTest.java#L191](../../src/test/java/com/elton/pixservice/infrastructure/web/controller/PixControllerRestAssuredTest.java#L191)). Atualizar código, Swagger e testes juntos. | D-01 a D-04 | Alta |
| R-03 | **[RECOMENDAÇÃO]** Definir o código do webhook para transição inválida (D-05). O 200 para evento repetido está correto. Para transição inválida, um 409 informa o provedor, mas pode gerar reenvios. Decidir junto com o provedor. | D-05 | Média |
| R-04 | **[RECOMENDAÇÃO]** Autenticar o webhook com assinatura HMAC sobre o corpo e um timestamp, ou com mTLS. | AC-03 | Crítica |
| R-05 | **[RECOMENDAÇÃO]** Usar `occurredAt` para ordenar eventos, ou removê-lo do contrato. | D-09 | Média |
| R-06 | **[RECOMENDAÇÃO]** Devolver a resposta original em idempotência repetida, e rejeitar o reuso da chave com corpo diferente (ex.: 422). | D-06, AC-09 | Média |
| R-07 | **[RECOMENDAÇÃO]** Adicionar código de erro estável (`code`) ao `ErrorResponse`, para o cliente não depender de texto livre. | §2.1 | Média |
| R-08 | **[RECOMENDAÇÃO]** Remover a chave Pix de mensagens de erro e de logs, ou mascará-la (ex.: `us***@example.com`). | AC-07 | Alta |
| R-09 | **[RECOMENDAÇÃO]** Tratar o fuso de `at` explicitamente: exigir `Z` ou offset e normalizar para UTC. | A5 | Média |
| R-10 | **[RECOMENDAÇÃO]** Versionar o path (`/v1`) antes de qualquer consumidor externo. Publicar o OpenAPI gerado como artefato do contrato, com a porta correta. | D-10 | Baixa |
| R-11 | **[RECOMENDAÇÃO]** Restringir `/actuator` e os cabeçalhos internos (`X-Upstream-Addr`) na borda do NGINX. | §7 | Média |
| R-12 | **[RECOMENDAÇÃO]** Corrigir o build e reativar os testes REST antes de considerar qualquer item acima como garantido. | §8, AC-01 | Pré-requisito |

---

## Apêndice — Fluxo ponta a ponta

Exemplo com banco limpo, em que as carteiras recebem os IDs 1 e 2:

```bash
# 1. Criar as carteiras de origem (1) e destino (2)
curl -s -X POST http://localhost:8089/wallets -H 'Content-Type: application/json' -d '{"userId":"alice"}'
curl -s -X POST http://localhost:8089/wallets -H 'Content-Type: application/json' -d '{"userId":"bob"}'

# 2. Registrar a chave Pix do destinatário (carteira 2)
curl -s -X POST http://localhost:8089/wallets/2/pix-keys -H 'Content-Type: application/json' -d '{"keyType":"EMAIL","keyValue":"bob@example.com"}'

# 3. Depositar 200,00 na origem (carteira 1)
curl -s -X POST http://localhost:8089/wallets/1/deposit -H 'Content-Type: application/json' -d '{"amount":200.00}'

# 4. Transferir 150,00. Cria a transferência PENDING e debita a origem (saldo 50,00)
curl -s -X POST http://localhost:8089/pix/transfers -H 'Content-Type: application/json' -H 'Idempotency-Key: req-0001' -d '{"fromWalletId":1,"pixKey":"bob@example.com","amount":150.00}'

# 5. Confirmar a liquidação com o endToEndId do passo 4. Espera-se 200 sem corpo
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8089/pix/webhook -H 'Content-Type: application/json' -d '{"endToEndId":"<endToEndId>","eventId":"evt-0001","eventType":"CONFIRMED","occurredAt":"2026-10-24T10:30:00"}'

# 6. Saldo do destinatário após a confirmação: 150,00
curl -s http://localhost:8089/wallets/2/balance
```

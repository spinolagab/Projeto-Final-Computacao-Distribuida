# API.md

## Objetivo
Especificar os endpoints do Serviço de Agendamento (Flask) e do Serviço Coordenador (locks - Node.js), formatos de request/response e HATEOAS. Este documento é o contrato que clientes e serviços irão seguir.

---

## Convenções
- Formato de data: RFC3339 UTC com milissegundos.
- Content-Type: `application/json`
- Autenticação: `Authorization: Bearer <token>`
- Todos os responses incluem `request_id` quando aplicável.
- HATEOAS: `links` no corpo com `rel`, `href`, `method`.

---

## Endpoints principais (Serviço de Agendamento)

### GET /time
**Descrição:** Retorna o tempo do servidor para sincronização.
**Request:** sem body  
**Response 200**
```json
{
  "server_time_utc":"2025-10-26T18:00:05.123Z",
  "server_unix_ms":1767080405123
}
```
**Observações:** Utilizar para algoritmo de Cristian no cliente.

---

### GET /telescopios
**Descrição:** Lista telescópios.
**Response 200**
```json
{
  "telescopes":[{"id":"hubble-acad","nome":"Hubble Academic","links":[{"rel":"self","href":"/telescopios/hubble-acad"}]}],
  "links":[{"rel":"create_booking","href":"/agendamentos","method":"POST"}]
}
```

---

### POST /agendamentos
**Descrição:** Cria um agendamento. Fluxo:
1. Recebe request do cliente (com `request_timestamp_utc` sincronizado).
2. Tenta adquirir lock: `POST http://coordenador:3000/locks` com `resource_id = <telescope_id>_<start_utc>`.
3. Se lock concedido: verifica conflitos no DB; se OK, grava Booking; gera AuditLogEntry; libera lock.
4. Se lock negado: retorna 409.

**Request**
```json
{
  "telescope_id":"hubble-acad",
  "cientista_id":7,
  "start_utc":"2025-12-01T03:00:00Z",
  "end_utc":"2025-12-01T03:05:00Z",
  "request_timestamp_utc":"2025-10-26T18:00:04.999Z",
  "purpose":"Observação"
}
```

**Responses**
- `201 Created`
```json
{
  "id":123,
  "telescope_id":"hubble-acad",
  "start_utc":"2025-12-01T03:00:00Z",
  "end_utc":"2025-12-01T03:05:00Z",
  "status":"CONFIRMED",
  "request_id":"req-20251026-9a1b2c",
  "links":[
    {"rel":"self","href":"/agendamentos/123","method":"GET"},
    {"rel":"cancel","href":"/agendamentos/123","method":"DELETE"},
    {"rel":"telescopio","href":"/telescopios/hubble-acad","method":"GET"}
  ]
}
```
- `409 Conflict` — body:
```json
{"error":"RESOURCE_LOCKED","conflict_owner":"servico-agendamento-1"}
```
- `400 Bad Request` — validação
- `401/403` — auth

**Headers úteis**
- `Retry-After` (quando apropriado)

---

### GET /agendamentos?telescopio={id}&from={start}&to={end}
**Descrição:** Lista agendamentos no intervalo.
**Response 200** com `links` para criar novo booking.

---

### GET /agendamentos/{id}
**Descrição:** Recupera agendamento.
**Response 200**:
- inclui `links` condicionais (ex: `cancel`, `edit`).

---

### DELETE /agendamentos/{id}
**Descrição:** Cancela agendamento (gera evento AUDIT `AGENDAMENTO_CANCELADO`).
**Response 200** com `links` (ex: `create`).

---

### PUT /agendamentos/{id}
**Descrição:** Atualiza agendamento; deve seguir fluxo de lock.
**Responses:** `200` / `409` / `400`

---

## Endpoints do Serviço Coordenador (Locks)

### POST /locks
**Request**
```json
{"resource_id":"hubble-acad_2025-12-01T03:00:00Z","owner_id":"servico-agendamento-1","ttl_seconds":30}
```
**Responses**
- `200 OK` (LOCKED)
```json
{"status":"LOCKED","resource_id":"...","acquired_at":"2025-10-26T18:00:05.120Z","ttl_seconds":30}
```
- `409 Conflict` (CONFLICT)
```json
{"status":"CONFLICT","resource_id":"...","owner_id":"servico-agendamento-2","acquired_at":"..."}
```

### DELETE /locks
**Request**
```json
{"resource_id":"...","owner_id":"servico-agendamento-1"}
```
**Responses:** `200` (RELEASED), `404`, `403`

### POST /locks/renew
**Descrição:** Renova TTL do lock (owner must match)
**Request**
```json
{"resource_id":"...","owner_id":"...","ttl_seconds":30}
```

### GET /locks/{resource_id}
**Response:** estado atual do lock (200/404)

---

## HATEOAS — Padrão
- Todos os recursos que representam entidades retornam um array `links` com objetos `{ "rel", "href", "method" }`.
- Objetivo: tornar o cliente capaz de navegar sem hardcode de URIs.

**Exemplo de agendamento (201)** já mostrado acima.

---

## Erros padronizados (body)
```json
{
  "error":"STRING_CODE",
  "message":"Human readable",
  "request_id":"req-...",
  "details": { ... optional ... }
}
```

---

## Cenários de Rejeição e Retentativa
- Se `POST /locks` retorna `409`, o servidor de aplicação deve retornar `409` ao cliente com `Retry-After` opcional.
- Política de retry no cliente recomendada: backoff exponencial com jitter.

---

## Segurança e Quotas
- Rate limiting por `cientista_id` e `IP`.
- Quotas mensais e policies por instituição.
- OAuth2/JWT com scopes (ex: `booking:create`, `booking:read`).

---

## Observabilidade
- Cada response inclui `request_id`.
- Métricas expostas: `lock_acquired_total`, `lock_conflict_total`, `booking_created_total`, `booking_conflict_total`, latências.

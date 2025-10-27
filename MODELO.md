# MODELOS.md

## Objetivo

Definir as entidades do domínio para o Sistema de Controle de Telescópio Espacial Compartilhado (SCTEC). Este arquivo serve como contrato entre diferentes microsserviços e DB.

---

## Convenções

- Todas as timestamps em **UTC** no formato RFC3339 com milissegundos, ex: `2025-10-26T18:00:05.123Z`.
- Campos `id` usam tipos adequados: integers para recursos auto-incrementais; UUIDs onde necessário.
- Campos `created_at` e `updated_at` gerados pelo servidor.
- Relacionamentos explicitados por foreign keys ou referências.

---

## Entidades

### Scientist

- **Descrição:** Usuário que pode solicitar tempo de observação.
- **Campos**
  - `id` (integer, PK)
  - `nome` (string, obrigatório)
  - `email` (string, único, obrigatório)
  - `instituicao` (string, opcional)
  - `roles` (array[string], ex: `["USER"]`, `["ADMIN"]`)
  - `created_at` (datetime UTC)
  - `updated_at` (datetime UTC)
- **Índices/Constraints**
  - `email` único
- **Uso em auditoria:** referenciado em `AuditLogEntry.details.cientista_id`

---

### Telescope

- **Descrição:** Recurso observável (e.g., Hubble-Acad).
- **Campos**
  - `id` (string, PK, ex: `hubble-acad`)
  - `nome` (string)
  - `descricao` (string)
  - `capabilities` (json) — campos como `{"max_exposure_min":120,"wavelengths":["UV","Visible"]}`
  - `created_at`, `updated_at`

---

### Booking (Agendamento)

- **Descrição:** Reserva confirmada ou tentativa de reserva.
- **Campos**
  - `id` (integer, PK)
  - `telescope_id` (FK -> Telescope.id)
  - `cientista_id` (FK -> Scientist.id)
  - `start_utc` (datetime RFC3339)
  - `end_utc` (datetime RFC3339)
  - `status` (enum: `PENDING`,`CONFIRMED`,`REJECTED`,`CANCELLED`)
  - `request_timestamp_utc` (datetime) — timestamp enviado pelo cliente (após sincronização)
  - `created_at`, `updated_at`
  - `audit_log_ref` (string) — id/hash do evento de auditoria
- **Regras**
  - `end_utc > start_utc`
  - duração compatível com `Telescope.capabilities`
  - overlaps verificados na camada de aplicação sob lock
- **Índices**
  - índice composto `(telescope_id, start_utc, end_utc)`

---

### Lock (coordenador) - Node.js

- **Descrição:** Representação temporária de exclusão mútua gerenciada pelo Serviço Coordenador.
- **Campos (mantidos no Coordenador)**
  - `resource_id` (string) — ex: `hubble-acad_2025-12-01T03:00:00Z`
  - `owner_id` (string)
  - `acquired_at` (datetime UTC)
  - `ttl_seconds` (integer)
- **Comportamento**
  - Concedido por `POST /locks`, liberado por `DELETE /locks` ou expirado por TTL.
  - Deve suportar renew (extensão do TTL) e inspeção (`GET /locks/{resource_id}`).

---

### AuditLogEntry

- **Descrição:** Registro imutável dos eventos de negócio em formato JSON.
- **Campos**
  - `id` (UUID v4 / hash)
  - `timestamp_utc` (datetime RFC3339 ms)
  - `level` (string) — `AUDIT`
  - `event_type` (string) — ex: `AGENDAMENTO_CRIADO`
  - `service` (string) — ex: `servico-agendamento`
  - `request_id` (string) — correlaciona logs de aplicação
  - `details` (object) — payload (ver LOGGING.md)
  - `signature` (string, optional) — HMAC/assinatura para verificar imutabilidade
- **Armazenamento recomendado**
  - Append-only JSONL + cópia para armazenamento imutável (S3 Object Lock, etc.)

---

### AuthUser / Token

- **Descrição:** Representa credenciais e escopos.
- **Campos**
  - `user_id` (FK -> Scientist.id)
  - `token` (string)
  - `scopes` (array[string])
  - `issued_at`, `expires_at`

---

## Relacionamentos

- `Scientist (1) -- (N) Booking`
- `Telescope (1) -- (N) Booking`
- `Booking (1) -- (N) AuditLogEntry`

---

## Exemplo de payloads

**Booking (request)**

```json
{
  "telescope_id": "hubble-acad",
  "cientista_id": 7,
  "start_utc": "2025-12-01T03:00:00Z",
  "end_utc": "2025-12-01T03:05:00Z",
  "request_timestamp_utc": "2025-10-26T18:00:04.999Z",
  "purpose": "Observação da Nebulosa X"
}
```

**AuditLogEntry (details exemplo)**

```json
{
  "agendamento_id": 123,
  "cientista_id": 7,
  "telescope_id": "hubble-acad",
  "start_utc": "2025-12-01T03:00:00Z",
  "end_utc": "2025-12-01T03:05:00Z",
  "request_timestamp_utc": "2025-10-26T18:00:04.999Z"
}
```

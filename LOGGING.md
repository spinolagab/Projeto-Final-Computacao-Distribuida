# LOGGING.md

## Objetivo
Definir o formato dos logs de auditoria e logs de aplicação para garantir rastreabilidade, integridade e suporte a disputas legais.

---

## Princípios
- **Audit logs**: append-only, imutáveis, formato JSON.
- **Application logs**: estruturados (JSON) e humanos (linha simples) para devs.
- **Correlações:** `request_id` em todos os logs relacionados.
- **Timestamps:** RFC3339 UTC com ms.

---

## Formato: AuditLogEntry (JSON)
Cada evento crítico de negócio gera um `AuditLogEntry` que contém os campos abaixo.

```json
{
  "id":"uuid-v4-or-sha256",
  "timestamp_utc":"2025-10-26T18:00:05.123Z",
  "level":"AUDIT",
  "event_type":"AGENDAMENTO_CRIADO",
  "service":"servico-agendamento",
  "request_id":"req-20251026-9a1b2c",
  "details": {
    "agendamento_id":123,
    "cientista_id":7,
    "telescope_id":"hubble-acad",
    "start_utc":"2025-12-01T03:00:00Z",
    "end_utc":"2025-12-01T03:05:00Z",
    "request_timestamp_utc":"2025-10-26T18:00:04.999Z"
  },
  "signature":"hmac-sha256:BASE64"
}
```

### Campos explicados
- `id`: UUID ou hash único do evento.
- `timestamp_utc`: quando o serviço registrou o evento.
- `event_type`: padrão padronizado.
- `service`: serviço que emitiu (ex: `servico-agendamento`, `coordenador`).
- `request_id`: correlaciona com logs de aplicação.
- `details`: payload com os campos essenciais do evento.
- `signature`: HMAC-SHA256 da linha JSON usando chave de auditoria rotacionável (recomendado).

---

## Formato: Application Log (texto + JSON)
Linha humana para consoles:
```
INFO:2025-10-26T18:00:04.500Z:servico-agendamento:Requisição recebida para POST /agendamentos request_id=req-20251026-9a1b2c
```
Versão estruturada para collectors:
```json
{
  "timestamp_utc":"2025-10-26T18:00:04.500Z",
  "level":"INFO",
  "service":"servico-agendamento",
  "message":"Requisição recebida para POST /agendamentos",
  "request_id":"req-20251026-9a1b2c",
  "remote_ip":"1.2.3.4",
  "path":"/agendamentos"
}
```

---

## Eventos de Auditoria recomendados
- `LOCK_ACQUIRED`
- `LOCK_RELEASED`
- `LOCK_CONFLICT`
- `AGENDAMENTO_CRIADO`
- `AGENDAMENTO_RECUSADO`
- `AGENDAMENTO_CANCELADO`
- `AGENDAMENTO_ATUALIZADO`

---

## Assinatura e Imutabilidade
- Calcular HMAC-SHA256 de cada linha JSON e salvar como `signature`.
- Guardar chave de HMAC em Key Management Service e rotacionar periodicamente.
- Manter cópias em armazenamento WORM (S3 Object Lock ou equivalente).

---

## Retenção e Exportação
- Audit logs: retenção mínima recomendada — 7 anos (ajustar conforme política institucional).
- Application logs: retenção configurável (ex: 90 dias).
- Export para investigações: JSONL + signatures + chain-of-custody metadata.

---

## Exemplos de fluxo de logging (sequência)
1. Application log: "Requisição recebida para POST /agendamentos" (`request_id`)
2. Application log: "Tentando adquirir lock" (`request_id`)
3. Coordinador emits `LOCK_ACQUIRED` audit event
4. Application emits `AGENDAMENTO_CRIADO` audit event (append-only)
5. Application releases lock and emits `LOCK_RELEASED` audit event

---

## Ferramentas recomendadas
- Collector: Filebeat/Fluentd -> ELK/EFK
- Storage imutável: S3 Object Lock, Azure Immutable Blob
- KMS para assinatura: AWS KMS / HashiCorp Vault

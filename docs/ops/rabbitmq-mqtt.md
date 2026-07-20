# RabbitMQ MQTT Bridge — Operations Runbook

This runbook covers how to configure RabbitMQ as an MQTT broker that feeds Navigator's
geofencing pipeline.

---

## Requirements

- **RabbitMQ 3.12+** — required so the MQTT plugin propagates the authenticated
  `user_id` on AMQP republish. Earlier versions do NOT set `user_id` on the
  AMQP message, which breaks the `EmployeeEventsBridge` employee-ID consistency
  check.
- **Erlang/OTP 26+** (recommended alongside RabbitMQ 3.12).

---

## Plugins to Enable

```bash
rabbitmq-plugins enable rabbitmq_mqtt rabbitmq_web_mqtt rabbitmq_auth_backend_http
```

Verify with:

```bash
rabbitmq-plugins list | grep -E "mqtt|auth_backend_http"
```

---

## `rabbitmq.conf` Example

```ini
# --------------------------------------------------------------------------
# MQTT listeners
# --------------------------------------------------------------------------

# Development: plain TCP on 1883
mqtt.listeners.tcp.default = 1883

# Production: TLS on 8883 (disable plain TCP in prod)
mqtt.listeners.ssl.default = 8883

# TCP options
mqtt.tcp_listen_options.backlog = 128
mqtt.tcp_listen_options.nodelay = true

# Keep-alive default (seconds); devices should negotiate their own
mqtt.keepalive = 60

# --------------------------------------------------------------------------
# TLS (production)
# --------------------------------------------------------------------------

# Point these at your organisation's certificate files.
# Do NOT commit cert paths to source control.
ssl_options.cacertfile = /etc/rabbitmq/certs/ca.pem
ssl_options.certfile   = /etc/rabbitmq/certs/server.pem
ssl_options.keyfile    = /etc/rabbitmq/certs/server.key
ssl_options.verify     = verify_peer
ssl_options.fail_if_no_peer_cert = false

# --------------------------------------------------------------------------
# Authentication: HTTP backend
# --------------------------------------------------------------------------

auth_backends.1 = http
auth_backends.2 = internal

auth_http.http_method       = post
auth_http.user_path         = http://localhost:8080/api/v1/mqtt/auth/user
auth_http.vhost_path        = http://localhost:8080/api/v1/mqtt/auth/vhost
auth_http.resource_path     = http://localhost:8080/api/v1/mqtt/auth/resource
auth_http.topic_path        = http://localhost:8080/api/v1/mqtt/auth/topic

# Timeout for auth HTTP calls (ms)
auth_http.request_timeout = 3000

# --------------------------------------------------------------------------
# AMQP default exchange for MQTT topic routing
# --------------------------------------------------------------------------

# MQTT topics are translated to AMQP routing keys on amq.topic.
# Topic: employees/123/location → routing key: employees.123.location
mqtt.exchange = amq.topic

# --------------------------------------------------------------------------
# Rate limiting (apply via policy, not conf)
# --------------------------------------------------------------------------

# See the Policy section below.
```

---

## Applying Rate-Limit Policies

Use `rabbitmqctl` or the Management UI to set per-connection and per-user
rate limits on the `amq.topic` exchange:

```bash
# Max 200 publishes per second per connection on amq.topic
rabbitmqctl set_policy mqtt-rate \
  "^amq\.topic$" \
  '{"max-connections-per-user": 50, "max-publishing-rate": 200}' \
  --apply-to exchanges

# Or use HTTP API
curl -u guest:guest -XPUT \
  http://localhost:15672/api/policies/%2F/mqtt-rate \
  -H "Content-Type: application/json" \
  -d '{
    "pattern": "^amq\\.topic$",
    "definition": {
      "max-connections-per-user": 50,
      "max-publishing-rate": 200
    },
    "apply-to": "exchanges"
  }'
```

---

## Navigator Config Keys Matrix

The following keys are added by the MQTT/geofencing feature. Set them in your
`.env` / environment.

| Key | Default | Dev | Prod | Description |
|-----|---------|-----|------|-------------|
| `USE_MQTT_BRIDGE` | `False` | `True` | `True` | Enable EmployeeEventsBridge |
| `MQTT_TOPIC_NAMESPACE` | `employees` | `employees` | `employees` | MQTT topic prefix |
| `MQTT_AUTH_CACHE_TTL` | `60` | `60` | `300` | Seconds to cache auth decisions |
| `MQTT_EVENT_DEDUP_TTL` | `600` | `60` | `600` | Dedup window in seconds |
| `MQTT_EVENT_DEDUP_REDIS_URL` | `CACHE_URL` | same | dedicated Redis | Redis URL for event dedup |
| `MQTT_ACCEPTED_SCHEMA_VERSIONS` | `1` | `1` | `1,2` | Accepted schema versions (comma-sep) |
| `MQTT_MAX_BATCH_SIZE` | `200` | `200` | `500` | Max positions in one batch |
| `MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY` | `True` | `True` | `True` | Reject mismatched employee IDs |
| `GEOFENCE_RELOAD_EXCHANGE` | `geofence.changed` | same | same | Fanout exchange for hot-reload |
| `GEOFENCE_COLLAPSE_INTRA_BATCH` | `True` | `True` | `True` | Collapse redundant intra-batch enter/exits |
| `GEOFENCE_DWELL_DURATION` | `300` | `60` | `300` | Dwell threshold in seconds |
| `GEOFENCE_HANDLER_TIMEOUT` | `5.0` | `5.0` | `10.0` | Per-handler timeout in seconds |
| `EMPLOYEE_EVENTS_EXCHANGE` | `employee.events` | same | same | AMQP exchange for location events |
| `WEBHOOK_SIGNING_ALGORITHM` | `sha256` | `sha256` | `sha256` | HMAC algorithm for webhook signatures |

### `MQTT_JWT_SECRET` is intentionally NOT a Navigator config key

JWT signing and verification is handled exclusively by `navigator_auth`.
Decoupling the JWT secret from Navigator config is a security feature — it
ensures the signing key is not accidentally logged or exposed through Navigator's
configuration introspection endpoints.

---

## TLS Certificate Provisioning Checklist

1. Generate a CA and server certificate using your organisation's PKI.
2. Place `ca.pem`, `server.pem`, and `server.key` in `/etc/rabbitmq/certs/`.
3. Ensure the RabbitMQ process user (`rabbitmq`) has read access.
4. Update `rabbitmq.conf` `ssl_options.*` paths.
5. Reload: `systemctl reload rabbitmq-server` or `rabbitmqctl eval 'ok.'`.
6. Test: `openssl s_client -connect localhost:8883 -CAfile /etc/rabbitmq/certs/ca.pem`.

---

## Troubleshooting

### Bridge DLQ Paths

Messages that fail validation are routed to dead-letter queues:

| DLQ name | Cause |
|----------|-------|
| `employee.events.dlq.schema` | Wrong schema version |
| `employee.events.dlq.envelope` | Missing `employee_id`, `type`, or `positions` |
| `employee.events.dlq.batch_size` | `positions` exceeds `MQTT_MAX_BATCH_SIZE` |
| `employee.events.dlq.empty_batch` | `positions` is empty |
| `employee.events.dlq.employee_id_mismatch` | AMQP `user_id` ≠ payload `employee_id` |
| `employee.events.dlq.unknown_type` | Unrecognised `type` field |

Inspect DLQ messages:

```bash
rabbitmqadmin get queue=employee.events.dlq.schema count=10
```

### Verifying `user_id` Propagation

1. Connect an MQTT client (e.g., `mosquitto_pub`) authenticated as employee `emp-123`.
2. Publish to `employees/emp-123/location`.
3. Inspect the republished AMQP message:

```bash
rabbitmqadmin get queue=employee.events.ingest count=1
# Look for the `user_id` property in the output
```

If `user_id` is absent, your RabbitMQ is older than 3.12 or the MQTT plugin
is not propagating the property. Upgrade to 3.12+.

### Auth Callback Errors

- Check Navigator logs for `mqtt_auth_user`, `mqtt_auth_topic` handler log lines.
- Confirm Navigator is reachable from RabbitMQ's network at the configured
  `auth_http.*_path` URLs.
- Auth responses must be plain-text `allow`/`deny`/`refuse` — JSON responses
  are NOT accepted by `rabbitmq_auth_backend_http`.

### MQTT Connection Refused

- Verify plugins are enabled: `rabbitmq-plugins list | grep mqtt`.
- Check listener port: `rabbitmq-diagnostics listeners`.
- Inspect logs: `journalctl -u rabbitmq-server -n 100`.

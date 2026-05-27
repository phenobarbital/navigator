# Brainstorm: MQTT + RabbitMQ Broker with Geofencing

**Date**: 2026-05-27
**Author**: Jesus Lara
**Status**: ready-for-spec (Rounds 1-3 complete; all open questions resolved)
**Recommended Option**: Option A — Pure AMQP via RabbitMQ MQTT Plugin (no MQTT client in Navigator)

---

## Problem Statement

Navigator currently has partial broker support — `navigator/brokers/` exposes RabbitMQ
(`aiormq`), Redis pub/sub and AWS SQS as producers/consumers of internal events. There is
**no MQTT support and no geofencing layer** anywhere in the codebase.

We need to enable a workforce-style mobile app to publish high-frequency telemetry
(`employees/{employeeId}/location`, `…/status`, `…/events/check-in`, `…/events/incidents`)
over **MQTT/TLS** from devices, ingest those messages through Navigator, fan them out to
internal services on RabbitMQ (`employee.location.updated → location-service.queue,
analytics.queue, audit.queue`; `employee.incident.created → incident-service.queue,
notification-service.queue, audit.queue`), and **react to geofence enter/exit events**
in near real-time — pushing notifications back to the device, calling registered Python
handlers, hitting HMAC-signed webhooks, and forwarding to FCM push (iOS via FCM's APNs bridge in v1; native APNs deferred to v2).

**Canonical envelope (telemetry):** the mobile app sends **batched** location messages
(reduces radio + broker round-trips for high-frequency telemetry). The canonical envelope
on `employees/{employeeId}/location` is:

```json
{
  "eventId": "uuid-v4",
  "employeeId": "123",
  "type": "location.batch",
  "schemaVersion": 1,
  "positions": [
    { "lat": 19.43, "lng": -99.13, "ts": "2026-05-27T10:15:01.220Z" },
    { "lat": 19.44, "lng": -99.14, "ts": "2026-05-27T10:15:06.180Z" }
  ]
}
```

Single-position envelopes (`type: "location.single"`) are also supported as a degenerate
case (`positions: [...]` of length 1). Non-location events (`status`, `events/check-in`,
`events/incidents`) keep the flat envelope `{eventId, employeeId, type, schemaVersion, payload, timestamp}`.

The `eventId` is mandated as a v4 UUID per message and is used downstream for **idempotent
processing** (the geofence consumer remembers recent eventIds in a Redis TTL set to drop
duplicates from device retries / at-least-once delivery).

The end-state architecture (per the user):

```
[Mobile App]
    | MQTT over TLS
    v
[MQTT Broker]
    | bridge / consumer
    v
[Ingestion Service]
    | AMQP
    v
[RabbitMQ Exchange: employee.events]
    +--> location-service.queue
    +--> attendance-service.queue
    +--> notification-service.queue
    +--> analytics.queue
    +--> audit.queue
```

**Who is affected**: Navigator backend developers (new modules to register and configure),
mobile app developers (MQTT client + JWT auth + downlink subscriptions), and ops/devops
(RabbitMQ plugin enablement, TLS cert provisioning, PostGIS / DB schema migrations).

## Constraints & Requirements

Locked in during interactive discovery (Rounds 1, 2 and 3):

| # | Constraint | Decision |
|---|---|---|
| 1 | MQTT broker choice | **RabbitMQ MQTT plugin** (single broker for MQTT + AMQP). |
| 2 | Mobile auth | **JWT bearer** issued and validated by **`navigator_auth`** (reused — no separate MQTT-scoped JWT issuer). Mobile presents the standard `navigator_auth` token as the MQTT password; same signing key, same expiry policy, same revocation surface. MQTT-specific scopes (`mqtt.subscribe:employees.{id}.#`, `mqtt.publish:employees.{id}.#`) are added to the existing scope namespace. |
| 3 | Geofence engine | **In-memory Shapely R-tree** (per-process), loaded from DB, hot-reloaded via pub/sub on change. **Transition state (per-employee `inside` set) is in-memory per process in v1**; multi-instance duplicate-transition mitigation via downstream audit dedup. Redis-backed shared state is deferred to v2. |
| 4 | Notification fan-out | **Four channels in v1**: MQTT downlink topic, **FCM push (APNs skipped for v1)**, internal RabbitMQ fanout, **HMAC-signed webhooks**, and **in-process Python callbacks via a `@on_geofence_event(...)` decorator**. iOS coverage in v1 relies on FCM-via-APNs (Google's FCM-to-APNs bridge) rather than a direct APNs integration; a native `aioapns` provider can be added in v2 without dispatcher changes. |
| 5 | Topic → routing-key mapping | RabbitMQ MQTT plugin defaults (slashes → dots, `amq.topic` exchange). Canonical JSON envelope: `{eventId, employeeId, type, schemaVersion, positions[] \| payload, timestamp}` — `positions[]` for `type=location.batch`, `payload` for everything else. **No separate `location.single` type — single-fix messages are batches of length 1.** Ingestion bridge republishes to `employee.events` topic exchange with cleaner keys (`employee.location.updated`, `employee.incident.created`). For batched location messages, the bridge **fans out one AMQP message per position** into `employee.events` (carrying `eventId` + `positionIndex` in headers for traceability / dedup) — downstream consumers see a uniform per-position stream and don't need to know batching exists. |
| 5a | Idempotency | `eventId` (UUID v4) is stored in a Redis `SET` with TTL=`MQTT_EVENT_DEDUP_TTL` (default 10 min). The bridge skips republish on hit. Per-position dedup uses `{eventId}:{positionIndex}` as the key. Failure mode: Redis down → log + republish (better duplicate than lose data; downstream audit dedups). |
| 5b | Batch limits | `MQTT_MAX_BATCH_SIZE = 200` positions per envelope (oversize → DLQ). Realistic ceiling: mobile typically sends batches of 3–6 positions (one every 5–10 s, flushed every 30 s); 200 is intentionally generous. |
| 5c | Schema versioning | Bridge accepts `schemaVersion ∈ {N, N-1}` (rolling-upgrade window of one). Older or unknown versions → DLQ on `employee.events.dlq.schema`. v1 ships with `MQTT_ACCEPTED_SCHEMA_VERSIONS={1}`. |
| 5d | Employee-id consistency | The bridge **enforces** that the `employeeId` field in the envelope matches the MQTT username (which is validated against the JWT `sub` at connection time). Mismatch → DLQ + structured warning log including `mqtt_username`, `envelope_employee_id`, `eventId`, source IP. Defense-in-depth against a device with a valid JWT trying to impersonate another employee in the payload. |
| 6 | Geofence lifecycle | **DB-backed** in the existing app DB + **admin REST CRUD endpoints** + pub/sub reload via `geofence.changed` event (multi-instance safe). **Tenant scoping is mandatory in v1**: `geofences.tenant_id` is NOT NULL; the CRUD API and engine evaluator both filter by tenant. Tenant resolution at evaluation time uses the employee → tenant lookup already present in `navigator_auth` (cached). |
| 6a | Dwell-time transitions | **In v1**. Engine tracks per-`(employee_id, geofence_id)` `entered_at` timestamps; a `dwell` transition is emitted once the employee has been continuously inside a geofence for `GEOFENCE_DWELL_DURATION` (default 5 min, configurable per-geofence via an optional `dwell_seconds` column). Implementation is a per-process `asyncio` timer registry; timers are cancelled on exit and not persisted across restarts (acceptable in v1; v2 may persist via Redis if needed). |
| 7 | JWT validation on RabbitMQ | **`rabbitmq_auth_backend_http`** — Navigator exposes `/api/v1/mqtt/auth/{user,vhost,resource,topic}` endpoints; RabbitMQ HTTP-calls them per connection / per ACL check. Endpoints delegate JWT decoding/validation to `navigator_auth`'s existing helpers (no parallel JWT logic). |
| 8 | Runtime integration | **Navigator app-lifecycle pattern** (the convention used by other brokers): `BaseConnection.setup(app)` registers `on_startup`/`on_shutdown` signal handlers. See "Code Context — Existing" below for the *actual* shape of this pattern vs the misleading `BackgroundService` name. |
| 9 | Geofence shapes | Polygons via Shapely; backing storage as **GeoJSON or WKT** in a SQL column (PostGIS not required for in-memory eval). |
| 10 | Backwards compatibility | All new code lives in **new modules**. No breaking changes to `navigator/brokers/rabbitmq/`. New config keys are opt-in (`USE_MQTT_BRIDGE=false` by default). |
| 11 | Lazy loading | All MQTT-plugin-specific config and Shapely imports must be deferred (no module-load cost when `USE_MQTT_BRIDGE` is false). |
| 12 | Webhook security | **HMAC-SHA256 signatures**. Each registered webhook has its own `secret`; the dispatcher computes `X-Navigator-Signature: sha256=<hex>` over the canonical JSON body and sends `X-Navigator-Timestamp` to prevent replay. Webhook recipients verify with their stored secret. Per-webhook secrets are stored encrypted (reusing `navigator_auth`'s secret-storage primitives) in the same DB row as the webhook URL. |
| 13 | Rate-limiting on MQTT publish | **RabbitMQ policy layer** (not Navigator-side). Per-connection limits configured via `rabbitmq.conf` policies (`max-publishing-rate`, `max-connections-per-user`); documented in the ops runbook. Navigator does not add an additional rate-limiting layer because it would be redundant and would lose the per-connection granularity the broker already provides. |
| 14 | `evaluate_batch` lifecycle | **v1**: Python implementation that internally calls `evaluate(...)` per position (stable API surface). **v2**: when ingest sustains >5k positions/s OR the polygon set exceeds ~10k entries, migrate the inner loop to a Cython-compiled `.pyx` module under `navigator/ext/geofencing/_engine_fast.pyx` with a Python fallback. The Python surface (`evaluate_batch(employee_id, positions: list[Position]) -> list[GeofenceTransition]`) stays identical — Cython is a hot-path replacement, not an API change. |

---

## Code Context

This section captures **verified file:line references** for everything the spec/task
phases will rely on. Anything *not* listed under "Exists today" does **not exist** and
must be built.

### Exists today

| Symbol | File / Line | Notes |
|---|---|---|
| `BaseConnection(ABC)` | `navigator/brokers/connection.py:14` | Abstract methods: `connect`, `disconnect`, `publish_message(body, queue_name, **kw)`, `consume_messages(queue_name, callback, **kw)`, `process_message(body, properties)`. `setup(app)` at `:119` registers `app.on_startup.append(self.start)` + `app.on_shutdown.append(self.stop)` and stores instance at `app[self._name_]`. Holds a `DataSerializer`, `asyncio.Lock`, retry config. |
| `BrokerConsumer(ABC)` | `navigator/brokers/consumer.py:6` | Abstract: `event_subscribe(queue_name, callback)`, `subscriber_callback(message, body)`, `wrap_callback(callback, requeue_on_fail, max_retries)`. |
| `BrokerProducer(BaseConnection, ABC)` | `navigator/brokers/producer.py:16` | Queue-backed producer with N workers (default 4) draining an `asyncio.Queue`. `setup(app)` adds POST `/api/v1/broker/{broker_service}/publish_event` handler at `:64`. `service_auth` decorator at `:163` validates `navigator_session`. |
| `RabbitMQConnection(BaseConnection)` | `navigator/brokers/rabbitmq/connection.py:17` | Uses `aiormq.connect(dsn)`. Methods: `create_exchange(name, type='topic', durable=True)` at `:142`, `ensure_exchange` at `:175`, `publish_message(body, queue_name, routing_key, **kw)` at `:186`, `process_message(body, properties)` at `:238`, `wrap_callback(callback, requeue_on_fail, max_retries)` at `:279` (handles `x-retry` header with exponential backoff), `consume_messages(queue_name, callback, prefetch_count=1)` at `:356`. |
| `RMQConsumer(RabbitMQConnection, BrokerConsumer)` | `navigator/brokers/rabbitmq/consumer.py:19` | Init takes `exchange_name`, `exchange_type='topic'`, `routing_key='*'`, `queue_name`. `subscribe_to_events(exchange, queue_name, routing_key, callback, exchange_type='topic', durable=True, prefetch_count=1, requeue_on_fail=True, max_retries=3)` at `:78` does the full exchange-declare + queue-declare + bind + consume. |
| `RMQProducer(BrokerProducer, RabbitMQConnection)` | `navigator/brokers/rabbitmq/producer.py:15` | Thin combiner; inherits the worker queue from `BrokerProducer` and the publish path from `RabbitMQConnection`. |
| `BaseExtension(ABC)` | `navigator/extensions.py:23` | Convention for `navigator/ext/*` modules. Hooks: `on_startup`, `on_shutdown`, `on_cleanup`, `on_context`, `middleware`. `setup(app)` at `:58` registers into `app.extensions[name]`. |
| `RedisConnection(DBConnection)` | `navigator/ext/redis/__init__.py:8` | Reference shape for a new `navigator/ext/` module. |
| `DBConnection(BaseExtension)` | `navigator/ext/db/__init__.py:10` | Pattern: `on_startup` builds the async client, `on_cleanup` closes it, `app[self.name] = self.conn`. |
| `rabbitmq_dsn` + `RABBITMQ_*` config | `navigator/conf.py:219-226` | `USE_RABBITMQ`, `RABBITMQ_HOST/PORT/USER/PASS/VHOST`, `rabbitmq_dsn`, `BROKER_MANAGER_QUEUE_SIZE`. |
| Setup example | `examples/brokers/nav_rabbitmq_consumer.py` | Idiomatic pattern: `rmq = RMQConsumer(callback=cb); rmq.setup(app)`. |
| `aiormq` dependency | `pyproject.toml:71` | `aiormq>=6.8.1` already present. |

### Does NOT exist today (must be built or added)

- **No MQTT client library** in `pyproject.toml` — no `aiomqtt`, `paho-mqtt`, `gmqtt`, or `hbmqtt`.
- **No `navigator/brokers/mqtt/`** module.
- **No `navigator/ext/geofencing/`** module.
- **No geofence DB table** — no `geofences` table in any migration.
- **No `Shapely` / `pyproj`** dependency in `pyproject.toml`.
- **No `/api/v1/mqtt/auth/*` HTTP endpoints** — `rabbitmq_auth_backend_http` will need new handlers in Navigator.
- **No `@on_geofence_event` / `@subscriber` decorator** pattern in `navigator/brokers/` — existing consumers take `callback` callables in their constructor; there is no decorator-based registry.
- **No `USE_MQTT_*` / `MQTT_*` config keys** in `navigator/conf.py`.

### Important non-obvious facts

- The `BackgroundService` class at `navigator/background/service/__init__.py:24` is a **job queue + tracker** (used for `BackgroundQueue` / `TaskWrapper` / `JobTracker`). It is **NOT** the long-running broker-consumer pattern. The actual "broker service" pattern that `RMQConsumer` / `SQSConsumer` / `RedisConsumer` use is `BaseConnection.setup(app)` — which directly wires `app.on_startup.append(self.start)` and `app.on_shutdown.append(self.stop)`. When the constraint says "BackgroundService pattern", we mean *this* aiohttp-signal-handler pattern, not the `BackgroundService` class.
- The **RabbitMQ MQTT plugin auto-translates** between MQTT topics and AMQP topic-exchange routing keys: an MQTT publish on `employees/123/location` lands on `amq.topic` with routing key `employees.123.location`. Conversely, an AMQP publish to `amq.topic` with routing key `employees.123.notifications` is delivered to MQTT subscribers of `employees/123/notifications`. **This means Navigator can do BOTH ingest AND downlink without ever speaking MQTT directly** — a fact that drives Option A below.
- `RMQConsumer.subscribe_to_events` already accepts arbitrary `exchange` + `routing_key` arguments — it can subscribe to `amq.topic` with `employees.#` out of the box, no new transport code needed.
- The existing `BrokerProducer.event_publisher` POST route at `navigator/brokers/producer.py:187` uses `@service_auth` against `navigator_session` (server-to-server auth). Mobile MQTT JWT auth is a **separate** concern handled by the RabbitMQ auth backend.
- **Batched location envelopes** (`type=location.batch` carrying a `positions[]` array) are the steady-state ingest shape. The bridge fans batches into per-position AMQP messages so the rest of the pipeline (geofence consumer, analytics, audit) sees a uniform per-position stream. This keeps the geofence engine's hot path simple (`evaluate(employee_id, lat, lon)` per position) and lets RabbitMQ's existing prefetch / QoS / retry semantics apply at per-position granularity.
- **Hot-path Cython opportunity (v2):** for sustained high-throughput batches, `GeofenceEngine.evaluate` (Shapely `STRtree.query` + `point.within(polygon)` + set-difference for transition computation) is a candidate for a Cython-compiled `evaluate_batch(employee_id, positions: list[tuple[float, float]])` method. Shapely 2's GEOS bindings already release the GIL on prepared geometry ops, so a Cython wrapper around a tight per-batch loop (single STRtree query + vectorized `prepared.contains` over candidates) is a measurable win once the in-memory R-tree exceeds ~10k polygons or sustained ingest exceeds ~5k positions/s. Not v1 scope; flagged here so the module layout (`engine.py` as pure Python with a clean `evaluate_batch` boundary) leaves the door open without ABI breakage.

---

## Options Explored

### Option A: Pure AMQP via RabbitMQ MQTT Plugin (Recommended)

**No MQTT client in Navigator.** RabbitMQ becomes both the AMQP and MQTT broker.
Navigator only ever speaks AMQP via the existing `aiormq` stack. Mobile clients
speak MQTT to RabbitMQ; the MQTT plugin translates topics to `amq.topic` routing keys
transparently. Notifications back to mobile are AMQP publishes on `amq.topic` with
`employees.123.notifications` — RabbitMQ delivers them to MQTT subscribers automatically.

**Components added:**

1. `navigator/brokers/rabbitmq/bridge.py` — `EmployeeEventsBridge(RMQConsumer)` subscribes
   to `amq.topic` with routing key `employees.#`, parses the JSON envelope, performs
   **eventId-based dedup** (Redis TTL set, configurable), **enforces employee-id
   consistency** (the `employeeId` field must equal the MQTT username extracted from
   `message.properties.user_id` — propagated by the RabbitMQ MQTT plugin from the
   authenticated JWT `sub`), and republishes to a new domain exchange `employee.events`
   (topic) with normalized routing keys (`employees.123.location` →
   `employee.location.updated`, `employees.123.events.incidents` →
   `employee.incident.created`). **For `type=location.batch` envelopes, the bridge fans
   the `positions[]` array into one AMQP message per position**, carrying `eventId`,
   `positionIndex`, `batchSize`, `tenantId` (resolved once per batch) in the message
   headers so downstream consumers can dedup at per-position granularity and trace back
   to the originating batch. Single-fix messages are batches of length 1 — no separate
   code path. The wiring of `employee.events` to `location-service.queue`,
   `analytics.queue`, `audit.queue`, etc. uses the existing `subscribe_to_events` API
   per consumer.
2. `navigator/brokers/rabbitmq/downlink.py` — `MQTTDownlinkPublisher(RMQProducer)` thin
   wrapper exposing `publish_to_employee(employee_id, topic, payload)` that publishes on
   `amq.topic` with the right key. Used by the notification dispatcher.
3. `navigator/ext/geofencing/` — new `BaseExtension`:
   - `engine.py` — `GeofenceEngine`: Shapely R-tree (`shapely.strtree.STRtree`),
     **per-tenant**: one R-tree per `tenant_id` (load_from_db builds them all; evaluate
     dispatches by the employee's tenant). Methods:
     `load_from_db()`, `evaluate(employee_id, lat, lon) -> list[GeofenceTransition]`,
     `evaluate_batch(employee_id, positions: list[Position]) -> list[GeofenceTransition]`
     (iterates `positions` in `ts` order, threads the per-employee `inside` set through,
     emits transitions on set changes; **collapses intra-batch flaps**: enter→exit→enter
     within the same batch yields one final `enter` rather than three transitions —
     configurable via `GEOFENCE_COLLAPSE_INTRA_BATCH=True` default),
     `reload_one(geofence_id)`, `_state: dict[employee_id, set[geofence_id]]` to detect
     enter vs exit vs stay, `_entered_at: dict[(employee_id, geofence_id), datetime]`
     to drive dwell-time emissions, `_dwell_timers: dict[(employee_id, geofence_id),
     asyncio.TimerHandle]` to schedule a `dwell` transition after
     `GEOFENCE_DWELL_DURATION` (default 5 min) of continuous presence. Dwell timers are
     cancelled on `exit`. The batch method exists primarily to make Cython optimization
     tractable later (see Constraint #14).
   - `models.py` — `Geofence` (id, name, polygon WKT/GeoJSON, **tenant_id NOT NULL**,
     active, dwell_seconds nullable for per-geofence overrides), `Position` (lat, lng,
     ts), `GeofenceTransition` (employee_id, geofence_id, tenant_id, kind:
     enter/exit/dwell, location, ts, source_event_id, dwell_duration nullable —
     populated only on `kind=dwell`).
   - `crud.py` — admin REST CRUD endpoints (`/api/v1/geofencing/fences`) + publishes
     `geofence.changed` to RabbitMQ for hot reload. Endpoints enforce tenant isolation
     via the requesting user's session tenant (a user can only CRUD geofences in their
     tenant; cross-tenant access requires a separate admin scope).
   - `dispatcher.py` — `NotificationDispatcher`: fan-out to (a) MQTT downlink topic via
     `MQTTDownlinkPublisher`, (b) **FCM push only in v1** via an HTTP v1 client (no
     APNs — iOS reached via FCM's APNs bridge), (c) internal RabbitMQ fanout exchange
     `geofence.notifications`, (d) **HMAC-SHA256-signed webhooks** (per-webhook secret;
     `X-Navigator-Signature: sha256=<hex>` over canonical JSON + `X-Navigator-Timestamp`),
     (e) in-process Python callbacks registered with the new decorator.
   - `decorators.py` — `@on_geofence_event(geofence_name=None, kind=None, employee_id=None,
     tenant_id=None)` registers a coroutine in a module-level registry; consumed by
     `NotificationDispatcher`. Concrete usage:

     ```python
     from navigator.ext.geofencing import on_geofence_event, GeofenceTransition

     @on_geofence_event(geofence_name="store_42", kind="enter")
     async def on_arrival_at_store_42(transition: GeofenceTransition):
         # transition.employee_id, .geofence_id, .tenant_id, .kind,
         # .location, .ts, .source_event_id, .dwell_duration
         await my_attendance_service.clock_in(
             transition.employee_id, at=transition.ts
         )

     @on_geofence_event(kind="dwell")  # any geofence, any tenant
     async def on_any_dwell(transition: GeofenceTransition):
         # fires after GEOFENCE_DWELL_DURATION (or per-geofence override)
         await log_extended_presence(transition)

     @on_geofence_event(tenant_id="acme", kind="exit")
     async def acme_exit_handler(transition: GeofenceTransition):
         await notify_supervisor(transition)
     ```

     Filters are conjunctive (`geofence_name` AND `kind` AND `employee_id` AND
     `tenant_id` must all match if specified); `None` means "any". Handlers run
     concurrently with a per-handler timeout (`GEOFENCE_HANDLER_TIMEOUT`, default 5s)
     and exceptions in one handler never block the others.
4. `navigator/handlers/mqtt_auth.py` — four aiohttp handlers for
   `rabbitmq_auth_backend_http`: `/api/v1/mqtt/auth/user`, `/vhost`, `/resource`, `/topic`.
   **Delegates JWT decoding/validation to `navigator_auth`'s existing helpers** (no
   parallel JWT logic; same signing key, same expiry semantics, same revocation surface).
   Validates the JWT (presented as MQTT password), checks scopes (an employee may only
   subscribe to `employees.{their_id}.#`; admin tokens get broader access), returns
   `allow` / `deny`. MQTT-specific scope namespace: `mqtt.subscribe:<pattern>`,
   `mqtt.publish:<pattern>` — added to `navigator_auth`'s scope registry.
5. `navigator/conf.py` additions: `USE_MQTT_BRIDGE`,
   `MQTT_TOPIC_NAMESPACE`, `MQTT_AUTH_CACHE_TTL`, `MQTT_EVENT_DEDUP_TTL` (Redis TTL for
   `eventId` dedup, default 600s), `MQTT_EVENT_DEDUP_REDIS_URL` (defaults to existing
   `CACHE_URL`), `MQTT_ACCEPTED_SCHEMA_VERSIONS` (default `{1}` — bridge rejects unknown
   versions to DLQ; accepts `{N, N-1}` during rolling upgrades),
   `MQTT_MAX_BATCH_SIZE` (default 200), `MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY`
   (default `True`), `GEOFENCE_RELOAD_EXCHANGE`, `GEOFENCE_COLLAPSE_INTRA_BATCH`
   (default `True`), `GEOFENCE_DWELL_DURATION` (default `300` sec / 5 min),
   `GEOFENCE_HANDLER_TIMEOUT` (default `5.0` sec), `EMPLOYEE_EVENTS_EXCHANGE`,
   `WEBHOOK_SIGNING_ALGORITHM` (default `"sha256"`). **Not added (intentionally):**
   `MQTT_JWT_SECRET` — JWT signing key continues to live in `navigator_auth`'s existing
   config; no duplication. `APNS_*` keys — APNs is out of scope for v1.
6. Ops docs: enabling `rabbitmq_mqtt`, `rabbitmq_web_mqtt`, and `rabbitmq_auth_backend_http`
   in `rabbitmq.conf`; sample policies; TLS listener config.

**Pros:**
- **Zero new MQTT runtime dependency** — `aiormq` covers everything. Smaller install footprint.
- **Smallest new transport surface** — reuses every line of the battle-tested `aiormq` retry / serialization / connection-monitor code in `RabbitMQConnection`.
- **Downlink for free** — publishing on `amq.topic` with the right routing key delivers to MQTT subscribers via the plugin. No separate MQTT client required for notifications.
- **Single broker to deploy, monitor, and secure.** One DSN, one cluster, one TLS cert chain.
- **Bridge is testable in isolation** — `EmployeeEventsBridge` is just an `RMQConsumer` subclass; integration tests need only a RabbitMQ container with the MQTT plugin enabled.
- **Auth is HTTP-only on Navigator's side** — no broker-specific JWT plugin to ship.

**Cons:**
- **Locked to RabbitMQ as the MQTT layer.** Migrating to a dedicated MQTT broker (EMQX/Mosquitto/VerneMQ) later requires adding a real MQTT client at that point.
- **MQTT-5-specific features** (shared subscriptions, message expiry, request/response correlation data) are limited to whatever the RabbitMQ MQTT plugin currently supports (MQTT 3.1.1 + partial MQTT 5).
- **High device fan-out ceiling.** The RabbitMQ MQTT plugin is fine for thousands of devices; beyond ~50k concurrent connections per node a dedicated MQTT broker is preferable.
- **Topic taxonomy coupling.** Renaming `employees/` topic prefix means coordinating mobile + bridge + auth code at once.

**Effort:** Medium

**Libraries / Tools:**

> **Note on dependency management:** Navigator is migrating to `uv`. New deps land via
> `uv add shapely`. The `pyproject.toml` edit listed under "Impact & Integration" is
> what `uv add` produces; we don't edit it by hand.

| Package | Purpose | Notes |
|---|---|---|
| `aiormq>=6.8.1` | AMQP transport | **Already in `pyproject.toml:71`** — no change. |
| `shapely>=2.0` | Geometry + R-tree (`shapely.strtree.STRtree`) | **NEW.** ~5 MB install. C-extensions, prebuilt wheels for all platforms. Add via `uv add shapely`. |
| `PyJWT>=2.8` | JWT validation in `/mqtt/auth/*` | **Already present** as a transitive dep via `navigator_auth`. JWT validation in the MQTT auth endpoints delegates to `navigator_auth`'s existing helpers — no separate JWT logic. |
| `aiohttp` | Existing | Used for FCM HTTP v1 calls, HMAC-signed webhook dispatch, and `/mqtt/auth/*` endpoints. No FCM SDK needed — straight HTTP POST with service-account JWT. |
| Existing: `redis.asyncio` | `eventId` dedup TTL set | Already pulled in via `navigator/ext/redis/` and `CACHE_URL`. |
| **Not added in v1**: `aioapns` | (would be APNs push provider) | iOS push in v1 goes through FCM's APNs bridge. Native `aioapns` integration deferred to v2; the dispatcher's push-provider abstraction is designed so adding it later is additive. |

**Existing Code to Reuse:**

- `navigator/brokers/rabbitmq/consumer.py:78` (`subscribe_to_events`) — entire ingestion bridge consumer.
- `navigator/brokers/rabbitmq/connection.py:186` (`publish_message`) — both the bridge republish path and the downlink publisher.
- `navigator/brokers/rabbitmq/connection.py:279` (`wrap_callback`) — automatic retry + x-retry header handling for bridge failures.
- `navigator/brokers/producer.py:16` (`BrokerProducer`) — queue-backed worker pattern for `MQTTDownlinkPublisher` (so the dispatcher doesn't block on broker latency).
- `navigator/brokers/connection.py:119` (`setup(app)`) — registration into aiohttp lifecycle.
- `navigator/ext/redis/__init__.py` — reference shape for `navigator/ext/geofencing/__init__.py`.
- `navigator/extensions.py:23` (`BaseExtension`) — base class for the geofencing ext.

---

### Option B: MQTT-Native Transport (`navigator/brokers/mqtt/`) + `ext/geofencing/` + Ingestion Bridge

Add a full first-class MQTT transport to Navigator that mirrors `navigator/brokers/rabbitmq/`
in structure: `MQTTConnection(BaseConnection)`, `MQTTConsumer(MQTTConnection, BrokerConsumer)`,
`MQTTProducer(BrokerProducer, MQTTConnection)`, backed by `aiomqtt` (the actively maintained
async wrapper around `paho-mqtt`). The MQTT consumer connects to RabbitMQ's MQTT plugin
(or any other MQTT broker), parses messages, and either calls handlers directly OR republishes
to a domain RabbitMQ exchange `employee.events` via the existing `RMQProducer`. The geofencing
ext is identical to Option A. JWT auth endpoints are identical to Option A.

**Pros:**
- **Broker-portable.** Same Navigator code works whether the MQTT broker is RabbitMQ, EMQX, Mosquitto, or VerneMQ — just change the connection DSN.
- **Native MQTT semantics.** Direct access to QoS, retained messages, last-will, MQTT 5 features (per `aiomqtt`'s feature matrix).
- **Reusable MQTTConsumer.** Any future Navigator use case beyond geofencing (IoT sensors, dashboards) gets a ready-made consumer.
- **MQTT-vs-AMQP split is testable in CI** with a Mosquitto container instead of a full RabbitMQ.

**Cons:**
- **New runtime dependency** (`aiomqtt` + `paho-mqtt`). Two transports to maintain in `navigator/brokers/`.
- **Two clients per Navigator instance** — one MQTT connection for ingest, one AMQP connection for republish. More moving parts, more failure modes.
- **Duplicated reconnect/retry logic.** `aiomqtt` has its own primitives; the parity with `RabbitMQConnection`'s retry semantics is manual work.
- **Downlink decision still needed.** Even with an MQTT producer, the design question of "do we publish notifications via AMQP (and let the plugin deliver) OR via MQTT directly?" doesn't go away — it just becomes a runtime config knob.

**Effort:** High

**Libraries / Tools:**

| Package | Purpose | Notes |
|---|---|---|
| `aiomqtt>=2.0` | Async MQTT 5 client | **NEW.** Wraps `paho-mqtt`; idiomatic `async for message in client.messages`. |
| `paho-mqtt>=2.0` | Underlying MQTT transport | **NEW** (transitive via `aiomqtt`). |
| `shapely>=2.0` | Same as Option A | **NEW.** |
| Everything else | Same as Option A | — |

**Existing Code to Reuse:**

- `navigator/brokers/connection.py:14` (`BaseConnection`) — base class for `MQTTConnection`.
- `navigator/brokers/consumer.py:6` + `producer.py:16` — base classes; structure mirrors RabbitMQ module.
- `navigator/brokers/rabbitmq/producer.py:15` — used as the AMQP republish path inside the bridge.
- Same geofencing / dispatcher / auth code as Option A — no change there.

---

### Option C: Monolithic `navigator/ext/employee_events/` All-in-One

Bundle everything — MQTT auth endpoints, the ingestion bridge, the geofence engine, the
notification dispatcher, the downlink publisher — into a single new `navigator/ext/employee_events/`
extension. Sub-modules exist internally but the public surface is one `EmployeeEventsExtension`
that you `setup(app)` and it brings up the whole stack.

**Pros:**
- **One-line install.** `EmployeeEventsExtension().setup(app)` configures the entire feature.
- **Self-contained.** Easy to ship, easy to remove, no cross-module wiring.
- **Clear ownership.** Everything related to the workforce-telemetry feature is in one tree.

**Cons:**
- **Violates Navigator's layering.** Transport belongs in `navigator/brokers/`, domain capabilities in `navigator/ext/`. Conflating them makes the bridge, downlink publisher, and auth endpoints non-reusable for any other domain (e.g. vehicle telemetry, IoT sensors).
- **Hides the broker semantics.** The bridge consumer and downlink publisher are *general-purpose* MQTT-RabbitMQ-plugin patterns — burying them inside an "employee events" ext means the next domain has to reimplement them.
- **Harder to test in isolation.** A monolithic ext means each test pulls in the geofence engine even when only the bridge or auth path is under test.
- **Configuration sprawl.** All new conf keys (`USE_MQTT_BRIDGE`, `MQTT_JWT_SECRET`, `GEOFENCE_RELOAD_EXCHANGE`, FCM keys, …) end up under one namespace, making partial adoption hard.

**Effort:** Medium-Low (less code organization, but more refactor debt later)

**Libraries / Tools:** Same as Option A.

**Existing Code to Reuse:** Same as Option A, but less of the existing layering benefit shows through.

---

## Recommendation: Option A

**Why:** The user's Round 1+2 choices already committed to:
- a single broker (RabbitMQ MQTT plugin),
- no future broker-portability requirement,
- the MQTT plugin's default topic/routing-key conventions,
- a bridge consumer that republishes to `employee.events`.

Given those decisions, **introducing a real MQTT client** (Option B) is over-engineering —
it pays an `aiomqtt` + `paho-mqtt` dependency cost and a second transport's worth of
retry/serialization plumbing to buy broker portability the user explicitly didn't ask for.

**Option C** is rejected on layering grounds: the bridge consumer and downlink publisher
are *general* RabbitMQ-MQTT-plugin patterns and belong next to `navigator/brokers/rabbitmq/`,
not buried inside an employee-events ext.

**Option A** uses the under-appreciated fact that the RabbitMQ MQTT plugin makes the
broker bidirectional from AMQP's perspective — ingest *and* downlink work without
Navigator ever opening an MQTT socket. The result is the smallest new code surface,
zero new transport dependency, and full reuse of Navigator's existing retry / serialization
/ reconnect machinery.

**What we trade away:** broker portability and any future need for MQTT-5-only features.
Both are acceptable per the user's choices. If portability is ever needed, Option B is the
incremental migration path — `MQTTConsumer` would slot in alongside the bridge with no
changes to the geofencing or auth layers.

---

## Feature Description

### User-facing behaviour

**Mobile devices:**
- Connect to RabbitMQ's MQTT TLS listener (port 8883).
- Authenticate with `username = employee_id` + `password = JWT` (issued by `navigator_auth` — the same token already used for HTTP API calls).
- Publish telemetry on `employees/{employeeId}/location|status|events/check-in|events/incidents` as JSON `{eventId, employeeId, type, schemaVersion, positions[] | payload, timestamp}`. Single-fix messages are batches of size 1.
- Subscribe to `employees/{employeeId}/notifications` to receive geofence-triggered notifications (enter / exit / dwell), push receipts, and ad-hoc messages from the backend.
- A device's JWT scopes restrict it to *its own* `employees/{employee_id}/#` subtree — enforced by Navigator's `/mqtt/auth/topic` endpoint (delegating to `navigator_auth`).

**Backend developers:**
- Register a Python handler with `@on_geofence_event(geofence_name="store_42", kind="enter")` (or `kind="dwell"`, or scoped by `tenant_id=...`) — the dispatcher invokes it when a matching event fires, no manual consumer wiring needed.
- Configure FCM service-account credentials and webhook URLs via `navigator/conf.py` and the `webhooks` admin endpoints; the dispatcher fans out automatically (FCM for push, HMAC-signed POST for webhooks). iOS reached via FCM's APNs bridge in v1.
- Subscribe additional service queues to `employee.events` (topic exchange) using the existing `RMQConsumer.subscribe_to_events` API.

**Admins (HR / ops):**
- CRUD geofences via REST: `POST/GET/PATCH/DELETE /api/v1/geofencing/fences`. Each geofence has name, polygon (GeoJSON), **tenant_id (mandatory)**, active, optional `dwell_seconds` override.
- CRUD webhooks via REST: `POST/GET/PATCH/DELETE /api/v1/geofencing/webhooks`. Each webhook has URL, encrypted HMAC secret, optional geofence filter, tenant_id.
- A geofence edit triggers a `geofence.changed` message on RabbitMQ; every running Navigator instance reloads its in-memory per-tenant R-tree.

### Internal behaviour

1. **Connection / auth path:** Mobile opens MQTT/TLS → RabbitMQ MQTT plugin calls `rabbitmq_auth_backend_http` → hits Navigator `/api/v1/mqtt/auth/user` with `username + password (JWT)` → handler **delegates JWT decoding/validation to `navigator_auth`'s existing helpers** (no parallel JWT logic), returns `allow tags=` + scope. Subsequent VHOST / resource / topic ACL checks call the matching Navigator endpoints, which evaluate the JWT's scope claims (including the new `mqtt.subscribe:*` / `mqtt.publish:*` scopes) against the requested topic. Optional in-memory TTL cache (configurable via `MQTT_AUTH_CACHE_TTL`) reduces per-publish overhead.
2. **Ingest path (batched location):** Mobile publishes one MQTT message on
   `employees/123/location` carrying `{eventId, employeeId:"123", type:"location.batch",
   schemaVersion:1, positions:[{lat,lng,ts}, ...]}` → RabbitMQ MQTT plugin places it on
   `amq.topic` with routing key `employees.123.location` → `EmployeeEventsBridge` (an
   `RMQConsumer` subscribed to `amq.topic` / `employees.#`) (a) checks `eventId` against
   the Redis dedup set, (b) validates `schemaVersion`, (c) **iterates `positions[]` and
   republishes one AMQP message per position** to `employee.events` with key
   `employee.location.updated`, carrying `{employeeId, lat, lng, ts}` in the body and
   `eventId` + `positionIndex` + `batchSize` in headers. Existing consumer queues
   (`location-service.queue`, `analytics.queue`, `audit.queue`, …) bind to
   `employee.events` and receive a uniform per-position stream. Non-batched events
   (`status`, `events/check-in`, `events/incidents`) follow the same path but produce
   exactly one AMQP message per MQTT message.
3. **Geofence evaluation:** A second consumer — `GeofenceConsumer` — also binds to
   `employee.events` with routing key `employee.location.updated`. On each message it
   resolves the employee's `tenant_id` (cached lookup via `navigator_auth`) and asks
   `GeofenceEngine.evaluate(employee_id, lat, lon)`, which selects the tenant's R-tree,
   finds candidate polygons, compares the result with the previous set of `inside`
   geofences for that employee (kept in a per-process dict keyed by `employee_id`), and
   emits `GeofenceTransition` objects for `enter` / `exit`. On `enter`, the engine
   schedules an `asyncio` timer for `dwell_seconds` (per-geofence override) or
   `GEOFENCE_DWELL_DURATION` (default 5 min); if not cancelled by an `exit`, the timer
   fires a `kind=dwell` transition. Because the bridge already split the batch, each
   evaluation is a single position — no intra-batch flap logic needed at this layer.
   (If a future deployment wants in-process batch evaluation to skip an AMQP hop,
   `evaluate_batch(...)` is available; not used in the v1 path.)
4. **Notification fan-out:** Each `GeofenceTransition` (enter / exit / dwell) is handed to `NotificationDispatcher.dispatch(transition)`. The dispatcher concurrently:
   - Calls all matching `@on_geofence_event` Python handlers (in-process, awaited concurrently with a per-handler timeout, filtered by `tenant_id`/`geofence_name`/`kind`/`employee_id`).
   - Publishes to RabbitMQ fanout exchange `geofence.notifications` so other internal services can consume.
   - Publishes on `amq.topic` with routing key `employees.{employee_id}.notifications` → reaches the mobile device via the MQTT plugin downlink.
   - POSTs to each configured webhook URL (filtered by tenant + optional geofence filter) with **HMAC-SHA256-signed** body (`X-Navigator-Signature: sha256=<hex>`, `X-Navigator-Timestamp: <unix>`).
   - POSTs to **FCM** (HTTP v1, service-account JWT) for off-device delivery. iOS handsets receive the FCM payload via FCM's APNs bridge. Native `aioapns` integration is deferred to v2 behind the same `PushProvider` interface.
5. **Geofence hot reload:** Admin CRUD endpoint mutates the DB row, then publishes a `geofence.changed` message on a fanout exchange. Every Navigator instance's `GeofenceEngine` subscribes to that exchange and calls `reload_one(id)` (or full `load_from_db()` on bulk changes).
6. **Lifecycle:** The whole stack registers via `setup(app)` (the existing broker pattern). On `app.on_startup`: connect to RabbitMQ, declare exchanges, load geofences from DB, start consumers, start downlink publisher workers, register HTTP handlers. On `app.on_shutdown`: drain queues, close channels, close connections.

### Edge cases & error handling

- **JWT expired mid-session** — RabbitMQ MQTT plugin already handles disconnects on auth failure on next ACL check; mobile retries with a fresh JWT.
- **`/mqtt/auth/*` endpoint slow** — RabbitMQ has per-call timeouts and an in-process cache; Navigator should respond in <50ms. We add `MQTT_AUTH_CACHE_TTL` on Navigator's side too.
- **Bridge can't parse envelope** — log + send to a dead-letter exchange (`employee.events.dlq`); do not block the queue.
- **Unknown `schemaVersion`** — bridge rejects to DLQ (`employee.events.dlq.schema`) so future versions can be processed by upgraded instances without losing data. `MQTT_ACCEPTED_SCHEMA_VERSIONS` is multi-valued for rolling upgrades.
- **Duplicate `eventId`** — Redis dedup set hit → bridge drops the message silently (logs at DEBUG). Dedup TTL must cover the device's retry window plus broker max delivery latency; default 10 minutes is conservative.
- **Redis dedup down** — bridge logs WARNING and republishes anyway (fail-open). Duplicates propagate downstream where audit and `_state: dict[employee_id, set[geofence_id]]` naturally deduplicate transitions (same-set evaluation = no transition emitted).
- **Oversized batch (`len(positions) > MQTT_MAX_BATCH_SIZE`, default 200)** — bridge rejects to DLQ to prevent a single misbehaving device from saturating downstream queues. Mobile devices should respect this limit; documented in mobile-integration runbook.
- **Empty `positions[]` array** — treated as malformed, sent to DLQ.
- **Geofence engine reload race** — `load_from_db()` builds the new R-tree fully, then swaps the reference atomically. No partial state.
- **Notification handler raises** — dispatcher catches per-channel; one failing handler doesn't block the others. Failed webhooks go to a retry queue with exponential backoff.
- **Out-of-order location messages** — engine compares ts against the last seen for that employee; if older, skip (configurable, default skip). Note: because the bridge preserves intra-batch order on republish, out-of-order is typically a cross-batch concern (e.g., mobile retried an older batch after a newer one delivered).
- **Employee in multiple geofences simultaneously** — engine tracks the *set* of geofences they're inside; only emits transitions on set change.
- **Multi-instance Navigator** — each instance maintains its own per-employee `inside` state; this means transition events can be duplicated across instances. Mitigation: deduplicate downstream (audit) or use a Redis-backed shared state (deferred to v2).
- **Geofence with self-intersecting polygon** — validated at CRUD time via `shapely.validation.explain_validity`; reject with 422.

---

## Capabilities

### New capabilities (kebab-case)

- `mqtt-bridge-ingest` — bidirectional MQTT/AMQP via RabbitMQ MQTT plugin; bridge consumer republishes to domain exchange, fans batched location envelopes into per-position AMQP messages.
- `mqtt-event-dedup` — Redis-TTL-set `eventId` deduplication on the bridge (per-position dedup via `{eventId}:{positionIndex}`); fail-open on Redis downtime.
- `mqtt-schema-validation` — envelope `schemaVersion` validation with DLQ on unknown versions; multi-version acceptance via `MQTT_ACCEPTED_SCHEMA_VERSIONS` for rolling upgrades.
- `mqtt-employee-id-enforcement` — bridge cross-checks envelope `employeeId` against the MQTT username (JWT `sub`) and DLQs mismatches.
- `mqtt-jwt-auth` — JWT-based per-connection auth for MQTT via `rabbitmq_auth_backend_http`, delegating to `navigator_auth`.
- `mqtt-downlink-publish` — push notifications to mobile via AMQP→MQTT plugin delivery.
- `geofence-engine` — per-tenant in-memory Shapely R-tree geofence evaluator with per-employee transition tracking and per-`(employee, geofence)` dwell timers; per-position `evaluate(...)` plus a batch-shaped `evaluate_batch(...)` whose hot path is a v2 Cython migration target.
- `geofence-crud-api` — tenant-scoped admin REST endpoints to manage geofences + pub/sub hot reload.
- `geofence-event-decorator` — `@on_geofence_event(geofence_name=..., kind=..., employee_id=..., tenant_id=...)` registry for in-process Python handlers (`kind ∈ {enter, exit, dwell}`).
- `notification-dispatcher` — multi-channel fan-out (MQTT downlink, FCM-only push, RabbitMQ fanout, HMAC-signed webhooks, Python callbacks).

### Modified capabilities

- None — all changes are additive. `navigator/brokers/rabbitmq/` gains new sibling modules (`bridge.py`, `downlink.py`) but its existing public API is unchanged.

---

## Impact & Integration

| Component | Change |
|---|---|
| `navigator/brokers/rabbitmq/__init__.py` | Export `EmployeeEventsBridge`, `MQTTDownlinkPublisher`. |
| `navigator/brokers/rabbitmq/bridge.py` | **NEW** — `EmployeeEventsBridge(RMQConsumer)`. |
| `navigator/brokers/rabbitmq/downlink.py` | **NEW** — `MQTTDownlinkPublisher(RMQProducer)`. |
| `navigator/ext/geofencing/` | **NEW** module: `__init__.py`, `engine.py`, `models.py`, `crud.py`, `dispatcher.py`, `decorators.py`, `push_providers/__init__.py`, `push_providers/fcm.py`, `webhooks.py` (HMAC signing helpers). _No `apns.py` in v1._ |
| `navigator/handlers/mqtt_auth.py` | **NEW** — `/api/v1/mqtt/auth/{user,vhost,resource,topic}` aiohttp handlers; delegates to `navigator_auth` helpers. |
| `navigator_auth` integration | **MODIFY** (light) — register MQTT scope namespace (`mqtt.subscribe:*`, `mqtt.publish:*`) into the existing scope registry. No new endpoints. |
| `navigator/conf.py` | **MODIFY** — append config keys listed under "conf.py additions" above. No `MQTT_JWT_SECRET`, no `APNS_*`. |
| `pyproject.toml` | **MODIFY** via `uv add shapely`. PyJWT confirmed already present (transitive via `navigator_auth`). |
| `docs/ops/rabbitmq-mqtt.md` | **NEW** — operator runbook for enabling `rabbitmq_mqtt`, `rabbitmq_web_mqtt`, `rabbitmq_auth_backend_http`, configuring TLS, sample policies, **per-connection rate-limit policies**. |
| `examples/brokers/nav_mqtt_bridge.py` | **NEW** — end-to-end example mirroring `examples/brokers/nav_rabbitmq_consumer.py`. |
| `examples/geofencing/basic_geofence.py` | **NEW** — example with `@on_geofence_event` handlers (enter/exit/dwell) + HMAC webhook + FCM push. |
| Database migration | **NEW** — `geofences` table (id, name, polygon, **tenant_id NOT NULL**, active, dwell_seconds nullable, created_at, updated_at) + `webhooks` table (id, url, secret_encrypted, tenant_id NOT NULL, geofence_filter nullable, active). Indexes on (tenant_id, active) for both. |

**No conflict** with any existing module — the changes are all additive new files plus four append-only edits (`conf.py`, `pyproject.toml`, `navigator/brokers/rabbitmq/__init__.py`, `navigator_auth` scope registry).

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the feature decomposes cleanly into:
  - Stream 1: MQTT auth endpoints + ops docs (no dependencies on other streams).
  - Stream 2: `EmployeeEventsBridge` (with `eventId` dedup + batch fan-out + `schemaVersion` validation) + `MQTTDownlinkPublisher` (only depends on existing `navigator/brokers/rabbitmq/` and `navigator/ext/redis/`).
  - Stream 3: `GeofenceEngine` (incl. `evaluate` + `evaluate_batch` API) + `models` + DB migration (pure logic, no broker dependency).
  - Stream 4: `crud.py` + hot-reload pub/sub (depends on Stream 3 + a small slice of Stream 2 for publishing reload events).
  - Stream 5: `NotificationDispatcher` + `@on_geofence_event` + push providers + webhooks (depends on Stream 2 downlink + Stream 3 engine for end-to-end testing).
- **Cross-feature independence**: No conflicts with in-flight specs in `sdd/proposals/` (`aiohttp-navigator-modernization` touches the app skeleton; `file-interfaces` touches `navigator/utils/file/`). Neither overlaps with `navigator/brokers/rabbitmq/`, `navigator/ext/`, `navigator/handlers/`, or `navigator/conf.py` in conflicting ways.
- **Recommended isolation**: **`mixed`**. Streams 1, 2, and 3 can each get their own worktree. Streams 4 and 5 sequence after 3 and 2 respectively, then everything converges in an integration worktree for the end-to-end example + ops runbook.
- **Rationale**: The natural module boundaries (auth handlers / bridge transport / geofence engine / dispatcher) map to non-overlapping file trees. Per-stream worktrees keep code review focused; the final integration step is small (wire-up + examples + docs).

---

## Decisions Log (Round 3)

All previously-open questions are now resolved. Decisions are reflected in the
Constraints table above; this log preserves traceability for spec phase.

| # | Question | Decision | Where applied |
|---|---|---|---|
| 1 | JWT issuer | **Reuse `navigator_auth`** to mint and validate JWTs. MQTT scopes added to existing scope namespace. No separate MQTT-scoped issuer. | Constraint #2, #7; `navigator/handlers/mqtt_auth.py`; conf (no `MQTT_JWT_SECRET`). |
| 2 | Tenant scoping in v1 | **Mandatory**. `geofences.tenant_id NOT NULL`; per-tenant R-tree in engine; CRUD enforces tenant isolation. | Constraint #6; `models.py`, `engine.py`, `crud.py`; DB migration. |
| 3 | FCM vs APNs in v1 | **FCM only**. iOS reached via FCM's APNs bridge. Native APNs deferred to v2 (dispatcher abstraction stays open). | Constraint #4; `dispatcher.py`; `push_providers/` (no `apns.py`); deps (no `aioapns`). |
| 4 | Webhook security | **HMAC-SHA256** with per-webhook secret. `X-Navigator-Signature: sha256=<hex>` + `X-Navigator-Timestamp` (anti-replay). Secrets stored encrypted via `navigator_auth` primitives. | Constraint #12; `webhooks.py`; `webhooks` DB table. |
| 5 | Transition state durability | **In-memory per process in v1**. Multi-instance duplicates handled by downstream audit dedup. Redis-backed shared state is a v2 concern. | Constraint #3; `engine.py`. |
| 6 | Dwell-time transitions | **In v1**. Per-`(employee, geofence)` `asyncio` timer registry; default 5 min, per-geofence override via `dwell_seconds`. Not persisted across restarts in v1. | Constraint #6a; `engine.py`; conf `GEOFENCE_DWELL_DURATION`. |
| 7 | Bridge employee_id consistency | **Enforced**. Mismatch between MQTT username (JWT `sub`) and envelope `employeeId` → DLQ + structured warning log. | Constraint #5d; `bridge.py`; conf `MQTT_ENFORCE_EMPLOYEE_ID_CONSISTENCY=True`. |
| 8 | MQTT rate-limiting layer | **RabbitMQ policy**, not Navigator-side. Configured in `rabbitmq.conf`; documented in ops runbook. | Constraint #13; `docs/ops/rabbitmq-mqtt.md`. |
| 9 | PyJWT presence | **Already present** as a transitive dep via `navigator_auth`. No explicit `uv add` needed. | Libraries table. |
| 10 | `location.single` vs `positions[]` | **Single canonical path through `positions[]`**. Single-fix messages are batches of length 1. | Constraint #5; `bridge.py`. |
| 11 | `MQTT_MAX_BATCH_SIZE` | **200** (oversize → DLQ). Realistic mobile batches are 3–6 positions. | Constraint #5b; conf. |
| 12 | `evaluate_batch` lifecycle | **v1**: Python (calls `evaluate` per position internally — stable API). **v2 Cython migration trigger**: sustained >5k positions/s OR polygon set >10k entries. Python surface stays identical. | Constraint #14; `engine.py`; `_engine_fast.pyx` (v2). |
| 13 | Schema version window | **Accept `{N, N-1}`** (one-version rolling-upgrade window). v1 ships `MQTT_ACCEPTED_SCHEMA_VERSIONS={1}`; bump to `{1, 2}` when v2 envelope rolls out. | Constraint #5c; conf. |

**No open questions remain for v1 scope.** Items intentionally deferred to v2:

- Native APNs provider (`aioapns`) — added without dispatcher changes.
- Redis-backed shared transition state for cross-instance dedup.
- Cython `evaluate_batch` hot-path migration (triggered on the metrics above).
- Persisted dwell timers across restarts.

---

## References

- RabbitMQ MQTT Plugin docs: https://www.rabbitmq.com/docs/mqtt
- RabbitMQ HTTP Auth Backend: https://github.com/rabbitmq/rabbitmq-server/tree/main/deps/rabbitmq_auth_backend_http
- `aiomqtt` (Option B fallback): https://github.com/empicano/aiomqtt
- Shapely STRtree: https://shapely.readthedocs.io/en/stable/strtree.html
- Existing Navigator brokers: `navigator/brokers/rabbitmq/{connection,consumer,producer}.py`
- BaseExtension pattern: `navigator/extensions.py:23`
- Setup example: `examples/brokers/nav_rabbitmq_consumer.py`
- `navigator_auth` (JWT issuer/validator reused for MQTT): existing module in Navigator stack.

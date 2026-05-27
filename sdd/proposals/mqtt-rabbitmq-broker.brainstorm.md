# Brainstorm: MQTT + RabbitMQ Broker with Geofencing

**Date**: 2026-05-27
**Author**: Jesus Lara
**Status**: exploration
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
handlers, hitting webhooks, and forwarding to FCM/APNs push providers.

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

Locked in during interactive discovery (Round 1 + Round 2):

| # | Constraint | Decision |
|---|---|---|
| 1 | MQTT broker choice | **RabbitMQ MQTT plugin** (single broker for MQTT + AMQP). |
| 2 | Mobile auth | **JWT bearer** issued by Navigator auth, validated per-connection. |
| 3 | Geofence engine | **In-memory Shapely R-tree** (per-process), loaded from DB, hot-reloaded via pub/sub on change. |
| 4 | Notification fan-out | **All five channels**: MQTT downlink topic, FCM/APNs push, internal RabbitMQ fanout, webhooks, and **in-process Python callbacks via a `@on_geofence_event(...)` decorator**. |
| 5 | Topic → routing-key mapping | RabbitMQ MQTT plugin defaults (slashes → dots, `amq.topic` exchange). JSON envelope: `{employee_id, event_type, timestamp, payload, schema_version}`. Ingestion bridge republishes to `employee.events` topic exchange with cleaner keys (`employee.location.updated`, `employee.incident.created`). |
| 6 | Geofence lifecycle | **DB-backed** in the existing app DB + **admin REST CRUD endpoints** + pub/sub reload via `geofence.changed` event (multi-instance safe). |
| 7 | JWT validation on RabbitMQ | **`rabbitmq_auth_backend_http`** — Navigator exposes `/api/v1/mqtt/auth/{user,vhost,resource,topic}` endpoints; RabbitMQ HTTP-calls them per connection / per ACL check. |
| 8 | Runtime integration | **Navigator app-lifecycle pattern** (the convention used by other brokers): `BaseConnection.setup(app)` registers `on_startup`/`on_shutdown` signal handlers. See "Code Context — Existing" below for the *actual* shape of this pattern vs the misleading `BackgroundService` name. |
| 9 | Geofence shapes | Polygons via Shapely; backing storage as **GeoJSON or WKT** in a SQL column (PostGIS not required for in-memory eval). |
| 10 | Backwards compatibility | All new code lives in **new modules**. No breaking changes to `navigator/brokers/rabbitmq/`. New config keys are opt-in (`USE_MQTT_BRIDGE=false` by default). |
| 11 | Lazy loading | All MQTT-plugin-specific config and Shapely imports must be deferred (no module-load cost when `USE_MQTT_BRIDGE` is false). |

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
   to `amq.topic` with routing key `employees.#`, parses the JSON envelope, normalizes the
   routing key (`employees.123.location` → `employee.location.updated`,
   `employees.123.events.incidents` → `employee.incident.created`), and republishes to a
   new domain exchange `employee.events` (topic). The wiring of `employee.events` to
   `location-service.queue`, `analytics.queue`, `audit.queue`, etc. uses the existing
   `subscribe_to_events` API per consumer.
2. `navigator/brokers/rabbitmq/downlink.py` — `MQTTDownlinkPublisher(RMQProducer)` thin
   wrapper exposing `publish_to_employee(employee_id, topic, payload)` that publishes on
   `amq.topic` with the right key. Used by the notification dispatcher.
3. `navigator/ext/geofencing/` — new `BaseExtension`:
   - `engine.py` — `GeofenceEngine`: Shapely R-tree (`shapely.strtree.STRtree`); methods
     `load_from_db()`, `evaluate(employee_id, lat, lon) -> list[GeofenceTransition]`,
     `reload_one(geofence_id)`, `_state: dict[employee_id, set[geofence_id]]` to detect
     enter vs exit vs stay.
   - `models.py` — `Geofence` (id, name, polygon WKT/GeoJSON, tenant_id, active),
     `GeofenceTransition` (employee_id, geofence_id, kind: enter/exit/dwell, location, ts).
   - `crud.py` — admin REST CRUD endpoints (`/api/v1/geofencing/fences`) + publishes
     `geofence.changed` to RabbitMQ for hot reload.
   - `dispatcher.py` — `NotificationDispatcher`: fan-out to (a) MQTT downlink topic via
     `MQTTDownlinkPublisher`, (b) FCM/APNs via an injected push provider, (c) internal
     RabbitMQ fanout exchange `geofence.notifications`, (d) configured webhooks (aiohttp
     POST), (e) in-process Python callbacks registered with the new decorator.
   - `decorators.py` — `@on_geofence_event(geofence_name=None, kind=None)` registers a
     coroutine in a module-level registry; consumed by `NotificationDispatcher`.
4. `navigator/handlers/mqtt_auth.py` — four aiohttp handlers for
   `rabbitmq_auth_backend_http`: `/api/v1/mqtt/auth/user`, `/vhost`, `/resource`, `/topic`.
   Validates the JWT (presented as MQTT password), checks scopes (an employee may only
   subscribe to `employees.{their_id}.#`), returns `allow` / `deny`.
5. `navigator/conf.py` additions: `USE_MQTT_BRIDGE`, `MQTT_JWT_SECRET`,
   `MQTT_TOPIC_NAMESPACE`, `MQTT_AUTH_CACHE_TTL`, `GEOFENCE_RELOAD_EXCHANGE`.
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

| Package | Purpose | Notes |
|---|---|---|
| `aiormq>=6.8.1` | AMQP transport | **Already in `pyproject.toml:71`** — no change. |
| `shapely>=2.0` | Geometry + R-tree (`shapely.strtree.STRtree`) | **NEW.** ~5 MB install. C-extensions, prebuilt wheels for all platforms. |
| `PyJWT>=2.8` | JWT validation in `/mqtt/auth/*` | Likely already present via `navigator_auth`; verify before adding. |
| `aiohttp` | Existing | Used for webhook dispatch and `/mqtt/auth/*` endpoints. |
| `aiohttp` (push) | FCM via HTTP v1 | No SDK — straight HTTP POST with service-account JWT. |
| Optional: `aioapns` | APNs push provider | Only if iOS push is in scope for v1. |

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
- Authenticate with `username = employee_id` + `password = JWT` (issued by Navigator auth).
- Publish telemetry on `employees/{employeeId}/location|status|events/check-in|events/incidents` as JSON `{employee_id, event_type, timestamp, payload, schema_version}`.
- Subscribe to `employees/{employeeId}/notifications` to receive geofence-triggered notifications, push receipts, and ad-hoc messages from the backend.
- A device's JWT scopes restrict it to *its own* `employees/{employee_id}/#` subtree — enforced by Navigator's `/mqtt/auth/topic` endpoint.

**Backend developers:**
- Register a Python handler with `@on_geofence_event(geofence_name="store_42", kind="enter")` — the dispatcher invokes it when a matching event fires, no manual consumer wiring needed.
- Configure FCM/APNs credentials and webhook URLs via `navigator/conf.py`; the dispatcher fans out automatically.
- Subscribe additional service queues to `employee.events` (topic exchange) using the existing `RMQConsumer.subscribe_to_events` API.

**Admins (HR / ops):**
- CRUD geofences via REST: `POST/GET/PATCH/DELETE /api/v1/geofencing/fences`. Each geofence has name, polygon (GeoJSON), tenant_id, active.
- A geofence edit triggers a `geofence.changed` message on RabbitMQ; every running Navigator instance reloads its in-memory R-tree.

### Internal behaviour

1. **Connection / auth path:** Mobile opens MQTT/TLS → RabbitMQ MQTT plugin calls `rabbitmq_auth_backend_http` → hits Navigator `/api/v1/mqtt/auth/user` with `username + password (JWT)` → Navigator validates the JWT, returns `allow tags=` + scope. Subsequent VHOST / resource / topic ACL checks call the matching Navigator endpoints, which evaluate the JWT's scope claims against the requested topic. Optional in-memory TTL cache (configurable via `MQTT_AUTH_CACHE_TTL`) reduces per-publish overhead.
2. **Ingest path:** Mobile publishes on `employees/123/location` → RabbitMQ MQTT plugin places message on `amq.topic` with routing key `employees.123.location` → `EmployeeEventsBridge` (an `RMQConsumer` subscribed to `amq.topic` / `employees.#`) parses the JSON envelope, normalizes the routing key, and publishes the validated message to `employee.events` with key `employee.location.updated` (or `employee.incident.created`, etc.). Existing consumer queues (`location-service.queue`, `analytics.queue`, `audit.queue`, …) bind to `employee.events` with the appropriate patterns and receive the message.
3. **Geofence evaluation:** A second consumer — `GeofenceConsumer` — also binds to `employee.events` with routing key `employee.location.updated`. On each message it asks `GeofenceEngine.evaluate(employee_id, lat, lon)`, which uses the Shapely R-tree to find candidate polygons, compares the result with the previous set of `inside` geofences for that employee (kept in a per-process dict), and emits `GeofenceTransition` objects for `enter` / `exit` (optionally `dwell` after N minutes).
4. **Notification fan-out:** Each `GeofenceTransition` is handed to `NotificationDispatcher.dispatch(transition)`. The dispatcher concurrently:
   - Calls all matching `@on_geofence_event` Python handlers (in-process, awaited concurrently with a per-handler timeout).
   - Publishes to RabbitMQ fanout exchange `geofence.notifications` so other internal services can consume.
   - Publishes on `amq.topic` with routing key `employees.{employee_id}.notifications` → reaches the mobile device via the MQTT plugin downlink.
   - POSTs to each configured webhook URL with signed payload.
   - POSTs to FCM/APNs (via the configured push provider) for off-device delivery.
5. **Geofence hot reload:** Admin CRUD endpoint mutates the DB row, then publishes a `geofence.changed` message on a fanout exchange. Every Navigator instance's `GeofenceEngine` subscribes to that exchange and calls `reload_one(id)` (or full `load_from_db()` on bulk changes).
6. **Lifecycle:** The whole stack registers via `setup(app)` (the existing broker pattern). On `app.on_startup`: connect to RabbitMQ, declare exchanges, load geofences from DB, start consumers, start downlink publisher workers, register HTTP handlers. On `app.on_shutdown`: drain queues, close channels, close connections.

### Edge cases & error handling

- **JWT expired mid-session** — RabbitMQ MQTT plugin already handles disconnects on auth failure on next ACL check; mobile retries with a fresh JWT.
- **`/mqtt/auth/*` endpoint slow** — RabbitMQ has per-call timeouts and an in-process cache; Navigator should respond in <50ms. We add `MQTT_AUTH_CACHE_TTL` on Navigator's side too.
- **Bridge can't parse envelope** — log + send to a dead-letter exchange (`employee.events.dlq`); do not block the queue.
- **Geofence engine reload race** — `load_from_db()` builds the new R-tree fully, then swaps the reference atomically. No partial state.
- **Notification handler raises** — dispatcher catches per-channel; one failing handler doesn't block the others. Failed webhooks go to a retry queue with exponential backoff.
- **Out-of-order location messages** — engine compares ts; if a message is older than the last seen for that employee, skip (configurable, default skip).
- **Employee in multiple geofences simultaneously** — engine tracks the *set* of geofences they're inside; only emits transitions on set change.
- **Multi-instance Navigator** — each instance maintains its own per-employee `inside` state; this means transition events can be duplicated across instances. Mitigation: deduplicate downstream (audit) or use a Redis-backed shared state (deferred to v2).
- **Geofence with self-intersecting polygon** — validated at CRUD time via `shapely.validation.explain_validity`; reject with 422.

---

## Capabilities

### New capabilities (kebab-case)

- `mqtt-bridge-ingest` — bidirectional MQTT/AMQP via RabbitMQ MQTT plugin; bridge consumer republishes to domain exchange.
- `mqtt-jwt-auth` — JWT-based per-connection auth for MQTT via `rabbitmq_auth_backend_http`.
- `mqtt-downlink-publish` — push notifications to mobile via AMQP→MQTT plugin delivery.
- `geofence-engine` — in-memory Shapely R-tree geofence evaluator with per-employee transition tracking.
- `geofence-crud-api` — admin REST endpoints to manage geofences + pub/sub hot reload.
- `geofence-event-decorator` — `@on_geofence_event(geofence_name=..., kind=...)` registry for in-process Python handlers.
- `notification-dispatcher` — multi-channel fan-out (MQTT downlink, FCM/APNs, RabbitMQ fanout, webhooks, Python callbacks).

### Modified capabilities

- None — all changes are additive. `navigator/brokers/rabbitmq/` gains new sibling modules (`bridge.py`, `downlink.py`) but its existing public API is unchanged.

---

## Impact & Integration

| Component | Change |
|---|---|
| `navigator/brokers/rabbitmq/__init__.py` | Export `EmployeeEventsBridge`, `MQTTDownlinkPublisher`. |
| `navigator/brokers/rabbitmq/bridge.py` | **NEW** — `EmployeeEventsBridge(RMQConsumer)`. |
| `navigator/brokers/rabbitmq/downlink.py` | **NEW** — `MQTTDownlinkPublisher(RMQProducer)`. |
| `navigator/ext/geofencing/` | **NEW** module: `__init__.py`, `engine.py`, `models.py`, `crud.py`, `dispatcher.py`, `decorators.py`, `push_providers/fcm.py`, `push_providers/apns.py` (optional). |
| `navigator/handlers/mqtt_auth.py` | **NEW** — `/api/v1/mqtt/auth/{user,vhost,resource,topic}` aiohttp handlers. |
| `navigator/conf.py` | **MODIFY** — append `USE_MQTT_BRIDGE`, `MQTT_JWT_SECRET`, `MQTT_TOPIC_NAMESPACE`, `MQTT_AUTH_CACHE_TTL`, `GEOFENCE_RELOAD_EXCHANGE`, `EMPLOYEE_EVENTS_EXCHANGE`, FCM/APNs creds. |
| `pyproject.toml` | **MODIFY** — add `shapely>=2.0`. Optional: `aioapns`. Verify `PyJWT` is already present (it should be via `navigator_auth`). |
| `docs/ops/rabbitmq-mqtt.md` | **NEW** — operator runbook for enabling `rabbitmq_mqtt`, `rabbitmq_web_mqtt`, `rabbitmq_auth_backend_http`, configuring TLS, sample policies. |
| `examples/brokers/nav_mqtt_bridge.py` | **NEW** — end-to-end example mirroring `examples/brokers/nav_rabbitmq_consumer.py`. |
| `examples/geofencing/basic_geofence.py` | **NEW** — example with `@on_geofence_event` handlers + webhook + push. |
| Database migration | **NEW** — `geofences` table (id, name, polygon, tenant_id, active, created_at, updated_at). |

**No conflict** with any existing module — the changes are all additive new files plus three append-only edits (`conf.py`, `pyproject.toml`, `navigator/brokers/rabbitmq/__init__.py`).

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the feature decomposes cleanly into:
  - Stream 1: MQTT auth endpoints + ops docs (no dependencies on other streams).
  - Stream 2: `EmployeeEventsBridge` + `MQTTDownlinkPublisher` (only depends on existing `navigator/brokers/rabbitmq/`).
  - Stream 3: `GeofenceEngine` + `models` + DB migration (pure logic, no broker dependency).
  - Stream 4: `crud.py` + hot-reload pub/sub (depends on Stream 3 + a small slice of Stream 2 for publishing reload events).
  - Stream 5: `NotificationDispatcher` + `@on_geofence_event` + push providers + webhooks (depends on Stream 2 downlink + Stream 3 engine for end-to-end testing).
- **Cross-feature independence**: No conflicts with in-flight specs in `sdd/proposals/` (`aiohttp-navigator-modernization` touches the app skeleton; `file-interfaces` touches `navigator/utils/file/`). Neither overlaps with `navigator/brokers/rabbitmq/`, `navigator/ext/`, `navigator/handlers/`, or `navigator/conf.py` in conflicting ways.
- **Recommended isolation**: **`mixed`**. Streams 1, 2, and 3 can each get their own worktree. Streams 4 and 5 sequence after 3 and 2 respectively, then everything converges in an integration worktree for the end-to-end example + ops runbook.
- **Rationale**: The natural module boundaries (auth handlers / bridge transport / geofence engine / dispatcher) map to non-overlapping file trees. Per-stream worktrees keep code review focused; the final integration step is small (wire-up + examples + docs).

---

## Open Questions

| # | Question | Owner | Notes |
|---|---|---|---|
| 1 | Which JWT issuer? Reuse `navigator_auth`'s existing token format, or mint a separate MQTT-scoped JWT? | Jesus Lara | Affects scope claim format (`mqtt.subscribe:employees.{id}.#` vs custom). |
| 2 | Tenant scoping — is `tenant_id` on geofences mandatory in v1, or single-tenant for now? | Jesus Lara | Drives DB schema and engine indexing. |
| 3 | FCM vs APNs vs both for v1? | Jesus Lara | APNs requires `aioapns` + a service-account certificate pipeline; if v1 is Android-only we skip it. |
| 4 | Webhook security model — HMAC signatures? mTLS? Just bearer header? | Jesus Lara | Spec-time decision; affects `dispatcher.py` + admin CRUD schema. |
| 5 | Geofence transition state durability — pure in-memory per process, or Redis-backed? | Jesus Lara | Memory is fine for v1 (transitions duplicate harmlessly across instances if audit dedups); Redis is a v2 concern. |
| 6 | Dwell-time transitions — required in v1 or deferred? | Jesus Lara | Adds an in-memory timer per (employee, geofence) pair. |
| 7 | Should the bridge enforce employee_id consistency between MQTT username and message envelope? | Jesus Lara | Defense-in-depth — recommended yes; cheap to implement at the bridge. |
| 8 | Rate-limiting on MQTT publish — RabbitMQ policy or Navigator-side? | Jesus Lara | RabbitMQ MQTT plugin supports per-connection limits; usually the right layer. |
| 9 | Confirm `PyJWT` is already a transitive dep (via `navigator_auth`)? If not, add explicitly. | Spec phase | Trivial to verify before spec. |

---

## References

- RabbitMQ MQTT Plugin docs: https://www.rabbitmq.com/docs/mqtt
- RabbitMQ HTTP Auth Backend: https://github.com/rabbitmq/rabbitmq-server/tree/main/deps/rabbitmq_auth_backend_http
- `aiomqtt` (Option B fallback): https://github.com/empicano/aiomqtt
- Shapely STRtree: https://shapely.readthedocs.io/en/stable/strtree.html
- Existing Navigator brokers: `navigator/brokers/rabbitmq/{connection,consumer,producer}.py`
- BaseExtension pattern: `navigator/extensions.py:23`
- Setup example: `examples/brokers/nav_rabbitmq_consumer.py`

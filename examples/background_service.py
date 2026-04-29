"""Navigator + BackgroundService example.

Levanta un Navigator Application con un BackgroundService registrado y
expone handlers HTTP (JSON) y una UI HTML para encolar tareas, consultar
su estado y recuperar el JobRecord completo.

Run:
    source .venv/bin/activate
    python examples/background_service.py

UI HTML (recomendado para probar desde el navegador):
    http://localhost:5000/ui

API JSON:
    curl -X POST http://localhost:5000/jobs \
        -H 'Content-Type: application/json' \
        -d '{"email": "alice@example.com", "message": "hi", "delay": 5}'
    curl http://localhost:5000/jobs/<task_id>
    curl http://localhost:5000/jobs/<task_id>/record
"""
import asyncio
import html
import uuid
from aiohttp import web

from navigator import Application
from navigator.background import (
    BackgroundService,
    BACKGROUND_SERVICE_KEY,
)
from app import Main


# ---------------------------------------------------------------------------
# Tareas de ejemplo (cualquier coroutine o callable funciona)
# ---------------------------------------------------------------------------
async def send_email(email: str, message: str, delay: int = 3) -> dict:
    """Simula el envío de un email tras esperar `delay` segundos."""
    await asyncio.sleep(delay)
    print(f"[send_email] -> {email}: {message}")
    return {"email": email, "delivered": True}


async def crunch_numbers(n: int) -> int:
    """Tarea CPU-light que devuelve un valor para inspeccionarlo en el record."""
    await asyncio.sleep(1)
    return sum(range(n))


# ---------------------------------------------------------------------------
# Navigator Application + BackgroundService
# ---------------------------------------------------------------------------
app = Application(Main)

BackgroundService(
    app=app.get_app(),
    max_workers=4,
    queue_size=16,
    tracker_type="memory",  # cambia a "redis" para persistencia entre procesos
)


def _get_service(request: web.Request) -> BackgroundService:
    """Helper: recupera el BackgroundService registrado en la app."""
    return request.app[BACKGROUND_SERVICE_KEY]


# ---------------------------------------------------------------------------
# Handlers HTTP
# ---------------------------------------------------------------------------
@app.post("/jobs")
async def submit_job(request: web.Request) -> web.Response:
    """Encola una tarea en el BackgroundService y devuelve el task_id."""
    data = await request.json()
    kind = data.get("kind", "email")
    service = _get_service(request)

    if kind == "email":
        record = await service.submit(
            send_email,
            data.get("email", "anon@example.com"),
            data.get("message", "hello"),
            delay=int(data.get("delay", 3)),
        )
    elif kind == "numbers":
        record = await service.submit(
            crunch_numbers,
            int(data.get("n", 1000)),
        )
    else:
        return web.json_response(
            {"error": f"unknown kind: {kind}"}, status=400
        )

    return web.json_response(
        {"task_id": record.task_id, "status": record.status},
        status=202,
    )


@app.get("/jobs/{task_id}")
async def job_status(request: web.Request) -> web.Response:
    """Devuelve solo el status del job."""
    task_id = request.match_info["task_id"]
    service = _get_service(request)
    try:
        status = await service.status(uuid.UUID(task_id))
    except ValueError:
        return web.json_response({"error": "invalid task_id"}, status=400)

    if status is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"task_id": task_id, "status": status})


@app.get("/jobs/{task_id}/record")
async def job_record(request: web.Request) -> web.Response:
    """Devuelve el JobRecord completo (status, result, error, timestamps)."""
    task_id = request.match_info["task_id"]
    service = _get_service(request)
    record = await service.record(task_id)
    if record is None:
        return web.json_response({"error": "not found"}, status=404)
    # `record` es un datamodel.BaseModel: .to_dict() lo serializa
    return web.json_response(record.to_dict(), status=200)


# ---------------------------------------------------------------------------
# UI HTML — encolar y consultar jobs desde el navegador
# ---------------------------------------------------------------------------
_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BackgroundService demo</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
  h1 { margin-bottom: 0.25rem; }
  h2 { margin-top: 2rem; }
  fieldset { border: 1px solid #ccc; border-radius: 6px; padding: 1rem 1.25rem; }
  label { display: block; margin: 0.5rem 0 0.15rem; font-size: 0.9rem; color: #444; }
  input { width: 100%; padding: 0.4rem 0.5rem; box-sizing: border-box; }
  button { margin-top: 1rem; padding: 0.5rem 1rem; cursor: pointer; }
  .row { display: flex; gap: 1rem; }
  .row > * { flex: 1; }
  small { color: #666; }
</style>
</head>
<body>
  <h1>BackgroundService</h1>
  <small>Encola tareas y revisa el resultado sin abrir Postman.</small>

  <h2>Encolar email</h2>
  <form method="get" action="/ui/enqueue">
    <input type="hidden" name="kind" value="email">
    <fieldset>
      <label>email</label>
      <input name="email" value="alice@example.com" required>
      <label>message</label>
      <input name="message" value="hello from the browser">
      <label>delay (segundos)</label>
      <input name="delay" type="number" min="0" value="3">
      <button type="submit">Submit</button>
    </fieldset>
  </form>

  <h2>Encolar crunch_numbers</h2>
  <form method="get" action="/ui/enqueue">
    <input type="hidden" name="kind" value="numbers">
    <fieldset>
      <label>n</label>
      <input name="n" type="number" min="1" value="1000" required>
      <button type="submit">Submit</button>
    </fieldset>
  </form>

  <h2>Consultar un job</h2>
  <form method="get" action="/ui/lookup">
    <fieldset>
      <label>task_id</label>
      <input name="task_id" placeholder="uuid devuelto al encolar" required>
      <button type="submit">Ver record</button>
    </fieldset>
  </form>
</body>
</html>
"""


def _render_job_page(task_id: str, body_html: str, *, refresh: bool = False) -> str:
    """Renderiza la página de detalle de un job."""
    refresh_meta = (
        '<meta http-equiv="refresh" content="2">' if refresh else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
{refresh_meta}
<title>job {html.escape(task_id)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
  pre {{ background: #f4f4f4; padding: 1rem; border-radius: 6px; overflow-x: auto; }}
  a {{ display: inline-block; margin-top: 1rem; }}
</style>
</head>
<body>
  <h1>Job <code>{html.escape(task_id)}</code></h1>
  {body_html}
  <a href="/ui">&larr; back</a>
</body>
</html>
"""


@app.get("/ui")
async def ui_index(request: web.Request) -> web.Response:
    """Landing page con formularios para encolar y consultar jobs."""
    return web.Response(text=_INDEX_HTML, content_type="text/html")


@app.get("/ui/enqueue")
async def ui_enqueue(request: web.Request) -> web.Response:
    """Encola un job a partir de querystring (compatible con <form method=get>)."""
    params = request.query
    kind = params.get("kind", "email")
    service = _get_service(request)

    if kind == "email":
        record = await service.submit(
            send_email,
            params.get("email", "anon@example.com"),
            params.get("message", "hello"),
            delay=int(params.get("delay", 3) or 3),
        )
    elif kind == "numbers":
        record = await service.submit(
            crunch_numbers,
            int(params.get("n", 1000) or 1000),
        )
    else:
        return web.Response(
            text=f"unknown kind: {html.escape(kind)}",
            status=400,
        )

    raise web.HTTPFound(f"/ui/jobs/{record.task_id}")


@app.get("/ui/lookup")
async def ui_lookup(request: web.Request) -> web.Response:
    """Redirige a la página HTML del task_id pedido en el form."""
    task_id = request.query.get("task_id", "").strip()
    if not task_id:
        raise web.HTTPFound("/ui")
    raise web.HTTPFound(f"/ui/jobs/{task_id}")


@app.get("/ui/jobs/{task_id}")
async def ui_job_detail(request: web.Request) -> web.Response:
    """Vista HTML del JobRecord, con auto-refresh mientras esté en curso."""
    task_id = request.match_info["task_id"]
    service = _get_service(request)
    record = await service.record(task_id)
    if record is None:
        body = "<p><strong>not found</strong></p>"
        return web.Response(
            text=_render_job_page(task_id, body),
            status=404,
            content_type="text/html",
        )

    data = record.to_dict()
    status = str(data.get("status", "")).lower()
    in_progress = status in {"pending", "running", "queued"}
    pretty = html.escape(_pretty_json(data))
    body = (
        f"<p><strong>status:</strong> {html.escape(status)}</p>"
        f"<pre>{pretty}</pre>"
    )
    if in_progress:
        body += "<p><small>auto-refresh cada 2s mientras el job esté activo</small></p>"
    return web.Response(
        text=_render_job_page(task_id, body, refresh=in_progress),
        content_type="text/html",
    )


def _pretty_json(data: dict) -> str:
    """Serializa el record a JSON indentado para mostrar en <pre>."""
    import json
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


if __name__ == "__main__":
    try:
        app.run()
    except KeyboardInterrupt:
        print("EXIT FROM APP =========")

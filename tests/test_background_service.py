"""Tests for BackgroundService with in-memory JobTracker and TTL cleanup."""
import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from navigator.background import BackgroundService, JobTracker


# -- helpers ------------------------------------------------------------------

async def blocking_task(duration: int = 15) -> dict:
    await asyncio.sleep(duration)
    return {"completed": True, "duration": duration}


def _build_app(tracker=None, **svc_kwargs):
    app = web.Application()
    service = BackgroundService(app, tracker=tracker, **svc_kwargs)

    async def submit_handler(request: web.Request) -> web.Response:
        duration = int(request.query.get("duration", "15"))
        job = await service.submit(blocking_task, duration)
        return web.json_response({"task_id": job.task_id, "status": job.status})

    async def status_handler(request: web.Request) -> web.Response:
        task_id = request.match_info["task_id"]
        rec = await service.tracker.status(task_id)
        if rec is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"task_id": rec.task_id, "status": rec.status})

    async def list_handler(request: web.Request) -> web.Response:
        jobs = await service.tracker.list_jobs()
        return web.json_response({
            "count": len(jobs),
            "jobs": [
                {"task_id": jid, "status": r.status}
                for jid, r in jobs.items()
            ],
        })

    app.router.add_post("/tasks", submit_handler)
    app.router.add_get("/tasks/{task_id}", status_handler)
    app.router.add_get("/tasks", list_handler)
    return app, service


# -- fixtures -----------------------------------------------------------------

@pytest.fixture
async def bg_client():
    app, service = _build_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client, service
    finally:
        await client.close()


@pytest.fixture
async def bg_client_short_ttl():
    tracker = JobTracker(ttl_seconds=2, reap_interval=1)
    app, service = _build_app(tracker=tracker)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client, service
    finally:
        await client.close()


# -- submit & status tests ----------------------------------------------------

class TestBackgroundServiceSubmit:

    async def test_submit_returns_task_id(self, bg_client):
        client, _service = bg_client
        resp = await client.post("/tasks?duration=1")
        assert resp.status == 200
        data = await resp.json()
        assert "task_id" in data
        assert data["status"] in ("pending", "running", "done")

    async def test_task_reaches_done(self, bg_client):
        """Submit a short task and confirm it finishes as done."""
        client, service = bg_client
        resp = await client.post("/tasks?duration=1")
        data = await resp.json()
        task_id = data["task_id"]

        # In same_loop mode the queue consumer awaits the task
        # on the event loop; give it time to finish.
        await asyncio.sleep(3)

        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "done"

    async def test_blocking_task_15s(self, bg_client):
        """Submit a 15-second blocking task and verify full lifecycle."""
        client, service = bg_client

        resp = await client.post("/tasks?duration=15")
        assert resp.status == 200
        data = await resp.json()
        task_id = data["task_id"]

        # Shortly after submission the task should be running.
        await asyncio.sleep(1.5)
        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "running", (
            f"expected running, got {data}"
        )

        # Wait for completion (15 s total, already waited ~1.5).
        await asyncio.sleep(16)
        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "done"

    async def test_unknown_task_returns_404(self, bg_client):
        client, _service = bg_client
        resp = await client.get("/tasks/nonexistent-id")
        assert resp.status == 404

    async def test_list_multiple_jobs(self, bg_client):
        client, _service = bg_client
        await client.post("/tasks?duration=3")
        await client.post("/tasks?duration=3")
        await asyncio.sleep(0.5)

        resp = await client.get("/tasks")
        data = await resp.json()
        assert data["count"] >= 2


# -- TTL cleanup tests --------------------------------------------------------

class TestJobTrackerTTLCleanup:

    async def test_completed_job_is_reaped(self, bg_client_short_ttl):
        """After TTL expires the finished job must disappear."""
        client, service = bg_client_short_ttl

        resp = await client.post("/tasks?duration=1")
        data = await resp.json()
        task_id = data["task_id"]

        # Check quickly after task finishes (~1 s) but before
        # TTL (2 s) expires so the reaper hasn't cleaned it yet.
        await asyncio.sleep(1.5)
        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "done"

        # Wait for TTL (2 s from finish) + reap interval (1 s) + margin.
        await asyncio.sleep(4)

        resp = await client.get(f"/tasks/{task_id}")
        assert resp.status == 404

    async def test_running_job_is_not_reaped(self, bg_client_short_ttl):
        """Running jobs must survive the reaper regardless of elapsed time."""
        client, service = bg_client_short_ttl

        # Duration must be > sleep below so the task is still running,
        # but short enough to finish within the queue's 5 s cleanup timeout.
        resp = await client.post("/tasks?duration=8")
        data = await resp.json()
        task_id = data["task_id"]

        # Wait well past TTL (2 s) + several reap cycles (1 s each).
        await asyncio.sleep(5)

        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "running"

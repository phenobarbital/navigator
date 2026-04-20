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
        resp = await client.post("/tasks?duration=2")
        assert resp.status == 200
        data = await resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"

    async def test_task_transitions_to_running(self, bg_client):
        client, _service = bg_client
        resp = await client.post("/tasks?duration=5")
        data = await resp.json()
        task_id = data["task_id"]

        await asyncio.sleep(1.5)

        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "running"

    @pytest.mark.timeout(25)
    async def test_blocking_task_15s(self, bg_client):
        """Submit a 15-second blocking task and verify full lifecycle."""
        client, _service = bg_client

        resp = await client.post("/tasks?duration=15")
        assert resp.status == 200
        data = await resp.json()
        task_id = data["task_id"]

        # should transition to running within ~1.5 s
        await asyncio.sleep(1.5)
        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "running"

        # wait for the task to finish (15 s total, already waited ~1.5)
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
        await client.post("/tasks?duration=60")
        await client.post("/tasks?duration=60")
        await asyncio.sleep(0.5)

        resp = await client.get("/tasks")
        data = await resp.json()
        assert data["count"] >= 2


# -- TTL cleanup tests --------------------------------------------------------

class TestJobTrackerTTLCleanup:

    async def test_completed_job_is_reaped(self, bg_client_short_ttl):
        """After TTL expires the finished job must disappear."""
        client, _service = bg_client_short_ttl

        resp = await client.post("/tasks?duration=1")
        data = await resp.json()
        task_id = data["task_id"]

        # wait for the task to finish
        await asyncio.sleep(3)
        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "done"

        # wait for TTL (2 s) + reap interval (1 s) + margin
        await asyncio.sleep(4)

        resp = await client.get(f"/tasks/{task_id}")
        assert resp.status == 404

    async def test_running_job_is_not_reaped(self, bg_client_short_ttl):
        """Running jobs must survive the reaper regardless of elapsed time."""
        client, _service = bg_client_short_ttl

        resp = await client.post("/tasks?duration=60")
        data = await resp.json()
        task_id = data["task_id"]

        # wait well past TTL + several reap cycles
        await asyncio.sleep(5)

        resp = await client.get(f"/tasks/{task_id}")
        data = await resp.json()
        assert data["status"] == "running"

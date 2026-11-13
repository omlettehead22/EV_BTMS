"""The PackTherm HTTP API (FastAPI). Start it with ``packtherm serve``.

A study is submitted as JSON (the study-file format), queued, and run in its
own process; the client checks its status, then fetches the results. One
server process holds the queue, so run a single instance (no extra uvicorn
workers). Interactive documentation is served at /docs; docs/API.md has examples.
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from .. import __version__
from .jobs import JobManager, QueueFull
from .settings import Settings


def _error(status: int, message: str, errors: list[str] | None = None, **extra) -> JSONResponse:
    body = {"error": message}
    if errors:
        body["errors"] = errors
    body.update(extra)
    return JSONResponse(body, status_code=status)


class RateLimiter:
    """Accepted studies per client per hour (a sliding window, in memory)."""

    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def retry_after(self, client: str, now: float | None = None) -> float | None:
        """Seconds until this client may submit again, or None if it may now."""
        now = time.time() if now is None else now
        q = self.hits[client]
        while q and now - q[0] >= 3600:
            q.popleft()
        return None if len(q) < self.per_hour else 3600 - (now - q[0])

    def record(self, client: str, now: float | None = None) -> None:
        self.hits[client].append(time.time() if now is None else now)


def create_app(settings: Settings | None = None, start_scheduler: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    manager = JobManager(settings)
    limiter = RateLimiter(settings.limits.rate_per_hour)
    lim = settings.limits

    @asynccontextmanager
    async def lifespan(_app):
        if start_scheduler:
            manager.start()
        yield
        manager.stop()

    app = FastAPI(
        title="PackTherm API",
        version=__version__,
        description="Battery thermal management design studies for cylindrical-cell packs. "
        "Submit a study (the study-file format, as JSON), check its status, then fetch the results.",
        lifespan=lifespan,
    )
    app.state.manager = manager
    app.state.limiter = limiter
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        size = request.headers.get("content-length")
        if size is not None and size.isdigit() and int(size) > lim.max_request_kB * 1024:
            return _error(413, f"request larger than {lim.max_request_kB} kB")
        return await call_next(request)

    def has_key(request: Request) -> bool:
        key = request.headers.get("x-api-key", "")
        return bool(key) and any(secrets.compare_digest(key, k) for k in settings.api_keys)

    def client_id(request: Request) -> str:
        if settings.trust_proxy and request.headers.get("x-forwarded-for"):
            return request.headers["x-forwarded-for"].split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def body_json(request: Request):
        raw = await request.body()
        if len(raw) > lim.max_request_kB * 1024:
            raise ValueError(f"request larger than {lim.max_request_kB} kB")
        import json

        try:
            return json.loads(raw or b"null")
        except ValueError as e:
            raise ValueError(f"not valid JSON: {e}") from None

    # -- information ------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "running": manager.running(), "queued": len(manager.queue)}

    @app.get("/limits")
    def limits():
        """The limits for requests without an API key."""
        return {k: getattr(lim, k) for k in lim.__dataclass_fields__}

    @app.get("/schema")
    def schema():
        """The study format as data: types, defaults and allowed values of every key."""
        from ..study import schema as study_schema

        return study_schema()

    @app.get("/template", response_class=PlainTextResponse)
    def template():
        """The commented study template (YAML), as ``packtherm template`` prints it."""
        from ..study import TEMPLATE

        return TEMPLATE

    @app.get("/cells")
    def cells():
        from ..cells import CELLS

        return {
            k: {
                "name": c.name,
                "model": c.model_label,
                "format": c.form_factor,
                "capacity_Ah": c.capacity_Ah,
                "V_nominal": c.V_nominal,
                "DCIR_25C_mOhm": c.R0_25C * 1e3,
                "mass_g": c.mass * 1e3,
            }
            for k, c in CELLS.items()
        }

    @app.post("/cells/check")
    async def check_cell(request: Request):
        """Check a user-defined cell; returns it as PackTherm understands it, with any warnings."""
        from ..user_cells import CellError, cell_summary, validate_cell

        try:
            doc = await body_json(request)
            spec, warnings = validate_cell(doc, "")
        except CellError as e:
            return _error(422, str(e).splitlines()[0].rstrip(":"), [x.strip() for x in str(e).splitlines()[1:]])
        except ValueError as e:
            return _error(400, str(e))
        return {"cell": spec, "derived": cell_summary(spec), "warnings": warnings}

    # -- studies ----------------------------------------------------------------
    @app.post("/studies", status_code=202)
    async def submit(request: Request):
        """Queue a study. Returns its id and where to check on it."""
        from ..study import StudyError, StudySpec, validate

        try:
            doc = await body_json(request)
        except ValueError as e:
            return _error(400, str(e))
        if (
            isinstance(doc, dict)
            and isinstance(doc.get("cell"), str)
            and doc["cell"].lower().endswith((".yaml", ".yml", ".json"))
        ):
            return _error(422, "Invalid study", ["cell: a file name cannot be used here; give the definition inline"])
        try:
            spec = validate(doc)
        except StudyError as e:
            return _error(422, "Invalid study", [x.strip() for x in str(e).splitlines()[1:]] or [str(e)])
        unlimited = has_key(request)
        study = StudySpec(spec).build()
        n = len(study.designs())
        if not unlimited:
            cap = lim.max_designs_fast if study.mode == "fast" else lim.max_designs_normal
            problems = []
            if n > cap:
                problems.append(f"design_space: {n} designs, more than the {cap} allowed in {study.mode} mode")
            hours = (study.duty.event_duration() + study.duty.rest_after_s) / 3600
            if hours > lim.max_simulated_h:
                problems.append(f"duty: {hours:.1f} h simulated (event and rest), more than {lim.max_simulated_h:g} h")
            steps = spec["duty"].get("steps") or []
            if len(steps) > lim.max_steps:
                problems.append(f"duty.steps: {len(steps)} segments, more than {lim.max_steps}")
            if problems:
                return _error(422, "Study over the limits (GET /limits)", problems)
            client = client_id(request)
            wait = limiter.retry_after(client)
            if wait is not None:
                return JSONResponse(
                    {"error": f"rate limit: {lim.rate_per_hour} studies per hour", "retry_after_s": round(wait)},
                    status_code=429,
                    headers={"Retry-After": str(int(wait) + 1)},
                )
        try:
            job = manager.submit(spec, unlimited)
        except QueueFull:
            return _error(503, f"the queue is full ({lim.max_queued} studies waiting); try again shortly")
        if not unlimited:
            limiter.record(client_id(request))
        return {
            "id": job.id,
            "state": job.state,
            "designs": n,
            "mode": study.mode,
            "status_url": f"/studies/{job.id}",
            "results_url": f"/studies/{job.id}/results",
        }

    def find(jid: str):
        job = manager.get(jid)
        return job, (None if job else _error(404, f"no study {jid!r} (results are kept {lim.keep_h:g} h)"))

    @app.get("/studies/{jid}")
    def status(jid: str):
        job, err = find(jid)
        if err:
            return err
        doc = job.status()
        if job.state == "queued":
            doc["queue_position"] = manager.position(jid)
        return doc

    def output(jid: str, kind: str, media: str):
        job, err = find(jid)
        if err:
            return err
        if job.state != "done":
            return _error(409, f"the study is {job.state}, not done", state=job.state)
        files = job.status()["files"] or {}
        return FileResponse(job.dir / files[kind], media_type=media, filename=files[kind])

    @app.get("/studies/{jid}/results")
    def results(jid: str):
        """The results document (the same JSON ``packtherm run`` writes)."""
        return output(jid, "json", "application/json")

    @app.get("/studies/{jid}/designs.csv")
    def designs_csv(jid: str):
        return output(jid, "csv", "text/csv")

    @app.get("/studies/{jid}/chart.png")
    def chart(jid: str):
        return output(jid, "chart", "image/png")

    @app.delete("/studies/{jid}")
    def cancel(jid: str):
        """Cancel a queued or running study, or delete a finished one and its results."""
        _, err = find(jid)
        if err:
            return err
        return {"id": jid, "result": manager.cancel_or_delete(jid)}

    return app

"""Study jobs: a queue, worker processes, progress, time limits and clean-up.

No database: each job is a folder under the jobs directory.

    <jobs_dir>/<id>/study.json     the validated study
    <jobs_dir>/<id>/status.json    state, times, files, error (written by the server)
    <jobs_dir>/<id>/progress.json  stage, done, total (written by the worker)
    <jobs_dir>/<id>/...            results JSON, designs CSV, chart (written by the worker)

Each running study is its own process, so a stuck or over-long study can be
stopped without touching the server, and a crash in one cannot take down
another. A scheduler thread starts queued studies, enforces the time limit,
and deletes finished jobs after ``keep_h``.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import secrets
import shutil
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .settings import Settings

STATES = ("queued", "running", "done", "failed", "cancelled")


def _write_json(path: Path, doc: dict) -> None:
    """Write atomically, so a reader never sees half a file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run_job(job_dir: str, workers: int) -> None:
    """Worker process: run one study and write its outputs into its folder."""
    d = Path(job_dir)
    try:
        from packtherm.study import StudySpec

        spec = StudySpec(json.loads((d / "study.json").read_text(encoding="utf-8")))
        last = [0.0]

        def progress(stage, done, total):
            now = time.monotonic()
            if done == total or now - last[0] > 0.5:  # at most twice a second
                last[0] = now
                _write_json(d / "progress.json", {"stage": stage, "done": done, "total": total})

        run = spec.run(workers=workers, progress=progress)
        paths = run.write(d)
        _write_json(d / "outputs.json", {k: p.name for k, p in paths.items()} | {"elapsed_s": run.elapsed_s})
    except Exception as e:  # noqa: BLE001 - any failure is reported to the client as the job's error
        (d / "error.txt").write_text(f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}", encoding="utf-8")
        raise SystemExit(1) from None


@dataclass
class Job:
    id: str
    dir: Path
    created: float
    unlimited: bool = False
    state: str = "queued"
    started: float | None = None
    finished: float | None = None
    error: str | None = None
    process: object = field(default=None, repr=False)

    def status(self) -> dict:
        doc = {
            "id": self.id,
            "state": self.state,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "error": self.error,
        }
        prog = _read_json(self.dir / "progress.json") or {}
        doc["progress"] = prog or None
        if self.state == "running" and prog.get("stage") == "designs" and prog.get("done"):
            elapsed = time.time() - (self.started or time.time())
            doc["eta_s"] = round(elapsed / prog["done"] * (prog["total"] - prog["done"]), 1)
        out = _read_json(self.dir / "outputs.json")
        doc["files"] = {k: v for k, v in out.items() if k != "elapsed_s"} if out else None
        return doc

    def save(self) -> None:
        _write_json(
            self.dir / "status.json",
            {k: getattr(self, k) for k in ("id", "created", "unlimited", "state", "started", "finished", "error")},
        )


class QueueFull(Exception):
    pass


class JobManager:
    """Owns every job: submit, status, cancel, delete; runs the scheduler thread."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.dir = settings.jobs_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.queue: deque[str] = deque()
        self.lock = threading.RLock()
        self.ctx = mp.get_context("spawn")  # a clean interpreter per study
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_cleanup = 0.0
        self._load()

    # -- lifecycle ------------------------------------------------------------
    def _load(self) -> None:
        """Pick up jobs from a previous run; ones that were not finished failed."""
        for sub in self.dir.iterdir():
            st = _read_json(sub / "status.json") if sub.is_dir() else None
            if not st:
                continue
            job = Job(
                st["id"],
                sub,
                st["created"],
                st.get("unlimited", False),
                st["state"],
                st.get("started"),
                st.get("finished"),
                st.get("error"),
            )
            if job.state in ("queued", "running"):
                job.state, job.error, job.finished = "failed", "the server restarted", time.time()
                job.save()
            self.jobs[job.id] = job

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="packtherm-scheduler", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        with self.lock:
            for job in self.jobs.values():
                if job.state == "running":
                    self._kill(job, "the server stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(0.2)

    # -- scheduling -------------------------------------------------------------
    def tick(self) -> None:
        """One scheduler pass: reap, time out, start, clean up."""
        lim = self.settings.limits
        now = time.time()
        with self.lock:
            for job in self.jobs.values():
                if job.state != "running":
                    continue
                p = job.process
                if p is not None and not p.is_alive():
                    p.join()
                    job.finished = now
                    if p.exitcode == 0 and (job.dir / "outputs.json").exists():
                        job.state = "done"
                    else:
                        job.state = "failed"
                        err = (
                            (job.dir / "error.txt").read_text(encoding="utf-8")
                            if (job.dir / "error.txt").exists()
                            else ""
                        )
                        job.error = err.split("\n\n")[0] or f"the study process exited with code {p.exitcode}"
                    job.process = None
                    job.save()
                elif job.started and not job.unlimited and now - job.started > lim.max_runtime_s:
                    self._kill(job, f"stopped after the {lim.max_runtime_s / 60:g}-minute time limit")
            while self.queue and self.running() < lim.max_running:
                job = self.jobs[self.queue.popleft()]
                p = self.ctx.Process(target=_run_job, args=(str(job.dir), self.settings.workers_per_study), daemon=True)
                p.start()
                job.process, job.state, job.started = p, "running", now
                job.save()
            if now - self._last_cleanup > 60:
                self._last_cleanup = now
                self.cleanup(now)

    def _kill(self, job: Job, reason: str, state: str = "failed") -> None:
        p = job.process
        if p is not None and p.is_alive():
            p.terminate()
            p.join(timeout=5)
            if p.is_alive():
                p.kill()
                p.join()
        job.process, job.state, job.error, job.finished = None, state, reason, time.time()
        job.save()

    def cleanup(self, now: float | None = None) -> int:
        """Delete jobs that finished more than keep_h ago; returns how many."""
        now = time.time() if now is None else now
        keep = self.settings.limits.keep_h * 3600
        gone = 0
        with self.lock:
            for jid in list(self.jobs):
                job = self.jobs[jid]
                if job.state in ("done", "failed", "cancelled") and job.finished and now - job.finished > keep:
                    shutil.rmtree(job.dir, ignore_errors=True)
                    del self.jobs[jid]
                    gone += 1
        return gone

    # -- requests ---------------------------------------------------------------
    def running(self) -> int:
        return sum(j.state == "running" for j in self.jobs.values())

    def submit(self, spec: dict, unlimited: bool = False) -> Job:
        with self.lock:
            if len(self.queue) >= self.settings.limits.max_queued:
                raise QueueFull
            jid = secrets.token_urlsafe(12)
            d = self.dir / jid
            d.mkdir()
            _write_json(d / "study.json", spec)
            job = Job(jid, d, time.time(), unlimited)
            job.save()
            self.jobs[jid] = job
            self.queue.append(jid)
        return job

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def position(self, jid: str) -> int | None:
        """1 for the next study to start; None if not queued."""
        try:
            return list(self.queue).index(jid) + 1
        except ValueError:
            return None

    def cancel_or_delete(self, jid: str) -> str:
        """Cancel a queued or running study, or delete a finished one. Returns what happened."""
        with self.lock:
            job = self.jobs[jid]
            if job.state == "queued":
                self.queue.remove(jid)
                job.state, job.finished, job.error = "cancelled", time.time(), "cancelled"
                job.save()
                return "cancelled"
            if job.state == "running":
                self._kill(job, "cancelled", state="cancelled")
                return "cancelled"
            shutil.rmtree(job.dir, ignore_errors=True)
            del self.jobs[jid]
            return "deleted"

"""API settings and limits, from environment variables with sensible defaults.

PACKTHERM_JOBS_DIR            where study jobs and their results live
PACKTHERM_API_KEYS            comma-separated keys; a request with one in the
                              X-API-Key header has no limits and no rate limit
PACKTHERM_TRUST_PROXY         1: take the client address from X-Forwarded-For
                              (set this behind a hosting platform's proxy)
PACKTHERM_CORS_ORIGINS        comma-separated origins allowed to call the API
                              from a browser ("*" by default: it is public)
PACKTHERM_WORKERS_PER_STUDY   processes each study uses (default 1)
PACKTHERM_LIMIT_<NAME>        any field of Limits, e.g. PACKTHERM_LIMIT_MAX_RUNNING=4
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    """What one study, and one visitor, may ask for (key holders are exempt)."""

    max_designs_fast: int = 120
    max_designs_normal: int = 40
    max_simulated_h: float = 24.0  # event plus rest
    max_steps: int = 1000  # segments in a custom duty
    max_runtime_s: float = 900.0  # a study is stopped after this
    max_running: int = 2  # studies at once (not exempt: it protects the machine)
    max_queued: int = 20  # waiting
    rate_per_hour: int = 10  # accepted studies per visitor per hour
    max_request_kB: int = 256
    keep_h: float = 24.0  # results are deleted this long after finishing


@dataclass(frozen=True)
class Settings:
    jobs_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "packtherm-jobs")
    limits: Limits = field(default_factory=Limits)
    api_keys: frozenset[str] = frozenset()
    trust_proxy: bool = False
    cors_origins: tuple[str, ...] = ("*",)
    workers_per_study: int = 1

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        lim = {}
        for f in fields(Limits):
            v = env.get(f"PACKTHERM_LIMIT_{f.name.upper()}")
            if v is not None:
                lim[f.name] = int(float(v)) if isinstance(f.default, int) else float(v)
        kw = {"limits": Limits(**lim)}
        if env.get("PACKTHERM_JOBS_DIR"):
            kw["jobs_dir"] = Path(env["PACKTHERM_JOBS_DIR"])
        keys = [k.strip() for k in env.get("PACKTHERM_API_KEYS", "").split(",") if k.strip()]
        kw["api_keys"] = frozenset(keys)
        kw["trust_proxy"] = env.get("PACKTHERM_TRUST_PROXY", "") in ("1", "true", "yes")
        origins = [o.strip() for o in env.get("PACKTHERM_CORS_ORIGINS", "*").split(",") if o.strip()]
        kw["cors_origins"] = tuple(origins)
        if env.get("PACKTHERM_WORKERS_PER_STUDY"):
            kw["workers_per_study"] = int(env["PACKTHERM_WORKERS_PER_STUDY"])
        return cls(**kw)

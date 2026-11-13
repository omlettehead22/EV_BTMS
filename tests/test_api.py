"""HTTP API: same results as packtherm run, validation, limits, keys, jobs."""

import json
import time

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from packtherm.api import Limits, Settings, create_app
from packtherm.study import StudySpec, validate

SMALL = {
    "packtherm_study": 1,
    "cell": "M50",
    "mode": "fast",
    "duty": {"type": "constant", "c_rate": 1.5},
    "design_space": {"topologies": ["ribbon"], "fillers": ["none"], "coolant_flows_g_s": [0.05], "chiller_C": []},
}
KEY = "test-key"


def client(tmp_path, **limits):
    s = Settings(jobs_dir=tmp_path / "jobs", limits=Limits(**limits), api_keys=frozenset({KEY}))
    app = create_app(s, start_scheduler=False)  # the tests drive the scheduler with tick()
    return TestClient(app), app.state.manager


def wait(manager, jid, states=("done", "failed", "cancelled"), timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        manager.tick()
        if manager.get(jid).state in states:
            return manager.get(jid).state
        time.sleep(0.1)
    raise TimeoutError(manager.get(jid).state)


def test_results_are_the_same_as_packtherm_run(tmp_path):
    c, m = client(tmp_path)
    r = c.post("/studies", json=SMALL)
    assert r.status_code == 202, r.text
    jid = r.json()["id"]
    assert c.get(f"/studies/{jid}/results").status_code == 409  # not done yet
    assert wait(m, jid) == "done"
    st = c.get(f"/studies/{jid}").json()
    assert st["progress"]["done"] == st["progress"]["total"]
    api = c.get(f"/studies/{jid}/results").json()
    direct = StudySpec(validate(SMALL)).run(workers=1)
    out = direct.write(tmp_path / "direct")
    assert c.get(f"/studies/{jid}/designs.csv").content == out["csv"].read_bytes()
    local = json.loads(out["json"].read_text())
    for k in ("created", "elapsed_s"):
        api.pop(k), local.pop(k)
    assert api == local
    assert c.get(f"/studies/{jid}/chart.png").headers["content-type"] == "image/png"


def test_invalid_studies_get_field_errors(tmp_path):
    c, _ = client(tmp_path)
    r = c.post("/studies", json={**SMALL, "mode": "turbo", "duty": {"type": "constant", "c_rate": -1}})
    assert r.status_code == 422
    errs = r.json()["errors"]
    assert any(e.startswith("mode:") for e in errs) and any(e.startswith("duty.c_rate:") for e in errs)
    r = c.post("/studies", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and "not valid JSON" in r.json()["error"]
    r = c.post("/studies", json={**SMALL, "cell": "/etc/my_cell.yaml"})
    assert r.status_code == 422 and "file name" in r.json()["errors"][0]


def test_limits_and_the_api_key(tmp_path):
    c, _ = client(tmp_path, max_designs_fast=1, max_simulated_h=2.0, max_request_kB=1)
    two = {**SMALL, "design_space": {**SMALL["design_space"], "topologies": ["ribbon", "bottom"]}}
    r = c.post("/studies", json=two)
    assert r.status_code == 422 and "more than the 1 allowed" in r.json()["errors"][0]
    assert c.post("/studies", json=two, headers={"X-API-Key": KEY}).status_code == 202
    assert c.post("/studies", json=two, headers={"X-API-Key": "wrong"}).status_code == 422
    long = {**SMALL, "duty": {"type": "constant", "c_rate": 0.1, "rest_h": 3}}
    assert "h simulated" in c.post("/studies", json=long).json()["errors"][0]
    big = {**SMALL, "name": "x" * 2000}
    assert c.post("/studies", json=big).status_code == 413


def test_rate_limit_and_full_queue(tmp_path):
    c, _ = client(tmp_path, rate_per_hour=2, max_queued=3)
    assert [c.post("/studies", json=SMALL).status_code for _ in range(3)] == [202, 202, 429]
    r = c.post("/studies", json=SMALL)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert c.post("/studies", json=SMALL, headers={"X-API-Key": KEY}).status_code == 202  # key: no rate limit
    assert c.post("/studies", json=SMALL, headers={"X-API-Key": KEY}).status_code == 503  # queue full (3)


def test_cancel_time_limit_restart_and_cleanup(tmp_path):
    slow = {**SMALL, "mode": "normal", "duty": {"type": "constant", "c_rate": 0.5}}
    c, m = client(tmp_path, max_running=1, max_runtime_s=1.0)
    a = c.post("/studies", json=slow).json()["id"]
    b = c.post("/studies", json=slow).json()["id"]
    m.tick()
    assert m.get(a).state == "running" and c.get(f"/studies/{b}").json()["queue_position"] == 1
    assert c.delete(f"/studies/{b}").json()["result"] == "cancelled"  # queued
    assert wait(m, a, ("failed",)) == "failed"
    assert "time limit" in c.get(f"/studies/{a}").json()["error"]
    d = c.post("/studies", json=SMALL, headers={"X-API-Key": KEY}).json()["id"]  # no time limit with a key
    m.tick()
    assert c.delete(f"/studies/{d}").json()["result"] == "cancelled"  # running
    assert m.get(d).process is None
    # A new server over the same folder keeps finished jobs and fails unfinished ones.
    e = c.post("/studies", json=SMALL).json()["id"]
    c2, m2 = client(tmp_path)
    assert m2.get(a).state == "failed" and m2.get(e).state == "failed" and "restarted" in m2.get(e).error
    assert m2.cleanup(time.time() + 25 * 3600) == 4
    assert c2.get(f"/studies/{a}").status_code == 404 and not (tmp_path / "jobs" / a).exists()


def test_information_endpoints(tmp_path):
    c, _ = client(tmp_path)
    assert c.get("/health").json()["status"] == "ok"
    s = c.get("/schema").json()
    assert s["top"]["mode"]["choices"] == ["normal", "fast"]
    assert s["duty"]["keys"]["c_rate"]["min"] == 0 and "RT42" in s["library"]["fillers"]
    assert c.get("/template").text.startswith("# PackTherm study file")
    assert c.get("/cells").json()["PF"]["model"] == "circuit (measured)"
    cell = {"name": "t", "format": 21700, "capacity_Ah": 5, "V_nominal": 3.6, "mass_g": 69, "DCIR_mOhm": 22}
    r = c.post("/cells/check", json=cell).json()
    assert r["derived"]["energy_density_Wh_L"] == pytest.approx(734, abs=1) and r["warnings"] == []
    r = c.post("/cells/check", json={**cell, "mass_g": 0.069})
    assert r.status_code == 422 and "grams" in r.json()["errors"][0]
    inline = {**SMALL, "cell": cell}
    assert c.post("/studies", json=inline).status_code == 202
    assert pd.Series(c.get("/limits").json())["rate_per_hour"] == 10

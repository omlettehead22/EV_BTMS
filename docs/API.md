# HTTP API

The API runs PackTherm studies for other programs and for the web app. A study is the same document as a [study file](STUDY_FILES.md), sent as JSON. It is queued and run in its own process; you check on it, then fetch the results.

```bash
pip install "packtherm[api]"
packtherm serve                       # http://127.0.0.1:8000, interactive docs at /docs
docker build -t packtherm . && docker run -p 8000:8000 packtherm
```

Run one server process: the queue lives in it, and each study runs in its own worker process. Results are files under the jobs folder and are deleted 24 hours after a study finishes; there is no database.

## A study, start to finish

```bash
# Submit: returns 202 with the study's id
curl -s -X POST localhost:8000/studies -H 'content-type: application/json' -d '{
  "packtherm_study": 1, "cell": "M50", "mode": "fast", "ambient_C": 35,
  "duty": {"type": "roadtrip"}
}'
# {"id": "SL82UpnfvWkA34tj", "state": "queued", "designs": 39, "mode": "fast",
#  "status_url": "/studies/SL82UpnfvWkA34tj", "results_url": "/studies/SL82UpnfvWkA34tj/results"}

# Check on it: state is queued, running, done, failed or cancelled
curl -s localhost:8000/studies/SL82UpnfvWkA34tj
# {"state": "running", "progress": {"stage": "designs", "done": 12, "total": 39}, "eta_s": 21.4, ...}

# When done: the results document, the designs table and the chart
curl -s localhost:8000/studies/SL82UpnfvWkA34tj/results > results.json
curl -s localhost:8000/studies/SL82UpnfvWkA34tj/designs.csv > designs.csv
curl -s localhost:8000/studies/SL82UpnfvWkA34tj/chart.png > chart.png
```

The results document is exactly what `packtherm run` writes for the same study ([format](STUDY_FILES.md#results-document)); a test checks this.

In Python:

```python
import time, requests

base = "http://127.0.0.1:8000"
study = {"packtherm_study": 1, "cell": "M50", "mode": "fast", "duty": {"type": "constant", "c_rate": 1.5}}
job = requests.post(f"{base}/studies", json=study).json()
while (s := requests.get(f"{base}/studies/{job['id']}").json())["state"] in ("queued", "running"):
    time.sleep(2)
results = requests.get(f"{base}/studies/{job['id']}/results").json()
print(results["summary"]["text"])
```

## Endpoints

| Request | Returns |
|---|---|
| `POST /studies` | 202 with `id`, `designs`, `mode`, `status_url`, `results_url`. 422 with `errors` (each naming its field) for an invalid study or one over the limits; 400 for invalid JSON; 413 for a request over the size limit; 429 over the rate limit (with `Retry-After`); 503 when the queue is full |
| `GET /studies/{id}` | `state`, `created` / `started` / `finished` (Unix time), `progress` (`stage`: `designs` then `re-check`, `done`, `total`), `eta_s` while running, `queue_position` while queued, `error` if failed, `files` when done |
| `GET /studies/{id}/results` | The results JSON (409 until the study is done) |
| `GET /studies/{id}/designs.csv`, `/chart.png` | The designs table and the trade-off chart |
| `DELETE /studies/{id}` | Cancels a queued or running study; deletes a finished one and its results |
| `GET /cells` | The cell library |
| `POST /cells/check` | Checks a [user-defined cell](STUDY_FILES.md#user-defined-cells): the cell with defaults, what PackTherm derives from it (energy density, density, cold resistance rise, thermal properties), and warnings. 422 with field errors |
| `GET /schema` | The study format as data: every key's type, default, allowed values and bounds, which duty keys each duty type uses, the user-defined cell keys, and the cells and fillers names may refer to |
| `GET /template` | The commented study template (YAML) |
| `GET /limits` | The limits below |
| `GET /health` | `status`, `version`, studies running and queued |
| `GET /docs` | Interactive documentation (OpenAPI) |

A user-defined cell goes inline in the study (`"cell": {...}`); file names are not accepted, since the server cannot read your files.

## Limits

For a public server, without an API key:

| Limit | Default | Setting |
|---|---|---|
| Designs per study, fast mode | 120 | `PACKTHERM_LIMIT_MAX_DESIGNS_FAST` |
| Designs per study, normal mode | 40 | `PACKTHERM_LIMIT_MAX_DESIGNS_NORMAL` |
| Simulated time (event and rest) | 24 h | `PACKTHERM_LIMIT_MAX_SIMULATED_H` |
| Segments in a custom duty | 1000 | `PACKTHERM_LIMIT_MAX_STEPS` |
| Run time per study | 15 min | `PACKTHERM_LIMIT_MAX_RUNTIME_S` |
| Studies per visitor per hour | 10 | `PACKTHERM_LIMIT_RATE_PER_HOUR` |
| Request size | 256 kB | `PACKTHERM_LIMIT_MAX_REQUEST_KB` |
| Studies running at once (all visitors) | 2 | `PACKTHERM_LIMIT_MAX_RUNNING` |
| Studies waiting (all visitors) | 20 | `PACKTHERM_LIMIT_MAX_QUEUED` |
| Results kept after finishing | 24 h | `PACKTHERM_LIMIT_KEEP_H` |

**API keys.** Set `PACKTHERM_API_KEYS` to a comma-separated list of keys. A request with a valid key in the `X-API-Key` header skips the per-study limits, the run-time limit and the rate limit; the running and queue limits still apply, as they protect the machine.

## Other settings

| Variable | Default | Meaning |
|---|---|---|
| `PACKTHERM_JOBS_DIR` | system temp folder | Where jobs and results are kept |
| `PACKTHERM_TRUST_PROXY` | off | `1` behind a hosting platform's proxy: the visitor's address comes from `X-Forwarded-For` (otherwise every visitor would share one rate limit) |
| `PACKTHERM_CORS_ORIGINS` | `*` | Origins allowed to call the API from a browser |
| `PACKTHERM_WORKERS_PER_STUDY` | 1 | Processes each study uses (designs run in parallel) |
| `PORT` | 8000 | Port for `packtherm serve` and the Docker image |

## Notes

- A server restart fails studies that were queued or running (`"error": "the server restarted"`); finished results survive in the jobs folder.
- Nothing in a request is run as code: studies are validated against the format before they are queued, and the server reads no files a request names.

# `/vehicle-summary` performance test

Load test for the heavy 10-table-join endpoint `GET /vehicle-summary`, built
with **[Locust](https://locust.io/)** — the Python equivalent of Gatling. It
provides a live web UI with real-time response-time / throughput charts and can
export a standalone **HTML report** plus CSV stats (the same kind of
visualization Gatling produces). No JVM / Scala needed; everything runs through
`uv`.

## Load profile

- **5s warm-up** — requests during this window are discarded from the report so
  cold S3 clients / DuckDB caches don't skew results.
- **60s measured window** targeting **~100 requests** (≈1.67 req/s, shaped via
  Locust `constant_throughput`).
- Requests are spread across a set of **verified joinable targets** (not just
  the BMW X1 1999 anchor) so different `model_year_id` branches are exercised.

## Prerequisites

The stack must be running and reachable at `http://localhost:8000`:

```bash
cd ../../infra && docker compose up -d --build
```

## Run

Headless (writes an HTML + CSV report under `reports/`):

```bash
./run.sh
```

Live web UI with Gatling-style charts at <http://localhost:8089>:

```bash
./run.sh web
```

## Tuning (environment variables)

| Variable          | Default                  | Meaning                                   |
| ----------------- | ------------------------ | ----------------------------------------- |
| `HOST`            | `http://localhost:8000`  | Target API base URL                       |
| `USERS`           | `1`                      | Concurrent simulated users                |
| `SPAWN_RATE`      | `1`                      | Users started per second                  |
| `WARMUP_SECONDS`  | `5`                      | Warm-up window (discarded from report)    |
| `RUN_SECONDS`     | `60`                     | Measured window                           |
| `TARGET_REQUESTS` | `100`                    | Requests spread across the measured window|

Example — push more concurrency:

```bash
USERS=10 TARGET_REQUESTS=500 ./run.sh
```

## Query targets

`BMW X1 1999` is the deterministic anchor. The other targets are real
`(manufacturer, model, year)` tuples sampled from the parquet data and verified
to return HTTP 200, e.g. `Maker_8867 / Model_14930 / 2008`,
`Maker_982 / Model_81534 / 2005`. Edit the `TARGETS` list in
[`locustfile.py`](locustfile.py) to change them.

## Output

After a headless run, open the generated `reports/report_<timestamp>.html` in a
browser for interactive charts (response times over time, percentiles, RPS).
`reports/` is git-ignored.

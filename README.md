# C.L.U.B Mini-hackathon — Fast Queries Under Pressure

## Requirements

- [UV](https://docs.astral.sh/uv/)
- Podman / Docker

## About it

A performance challenge built on a **working but intentionally slow** FastAPI
service. The API answers `GET /vehicle-summary` by joining **10 tables** stored
as Parquet files and queried through a local AWS emulator (Ministack: Athena +
S3, DuckDB engine).

![Architecture overview](docs/Arch_overview.png)

## What is the challenge

Make `GET /vehicle-summary` respond **as fast as possible** without changing
**what** it returns.

```
GET /vehicle-summary?manufacturer=BMW&model=X1&year=1999
```

- The response must stay **semantically correct** (same data, same shape).
- Any technique is fair game inside the constraints.

## How to run dependencies containerized

Start the infrastructure only — Ministack plus the one-shot S3 seeder — and
leave the API out so you can run and optimize it yourself.

```bash
docker compose -f infra/docker-compose.yml up -d ministack seed-init
```

Ministack listens on `http://localhost:4566`. The seeder loads the Parquet data into the `vehicle-data` bucket and then exits.

### Run the API yourself (locally, with uv)

From the repo root:

```bash
uv sync --project api --active
uv run --project api uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Check it is up on http://localhost:8000/docs (you can try the available endpoints)



## How to run the Load Test

The load test hammers `GET /vehicle-summary` with [Locust](https://locust.io/)
and produces an HTML + CSV report. The stack must be running and reachable at
`http://localhost:8000`.

```bash
cd tests/performance
./run.sh          # headless: warm-up + measured run, writes reports/report_<timestamp>.html
./run.sh web      # live web UI with charts at http://localhost:8089
```

See [tests/performance/README.md](tests/performance/README.md) for the full list.

## Test scenario

The official scoring run uses **15 users**, a **10 second** measured window and
**100 requests**:

```bash
cd tests/performance
USERS=15 RUN_SECONDS=10 TARGET_REQUESTS=100 ./run.sh
```

## Constraints

- ✅ You may **only** change files under the [`api/`](api/) folder.
- 🚫 Do **not** change the `/vehicle-summary` response schema (same data, same shape).
- 🚫 Do **not** relax the API container resource limits (0.5 CPU, capped RAM)
  defined in [infra/docker-compose.yml](infra/docker-compose.yml).

## How to submit your version

1. **Fork** this repository.
2. Make your changes (only under [`api/`](api/)).
3. Open a **pull request** against this repo's `main` branch.

Good luck, have fun!
# mini-hackathon-ctw

## Simple API

This repo now includes a minimal FastAPI app that reads all `.parquet` files from the `vehicle-data` bucket in LocalStack and exposes them at `GET /get_all`.

## Run everything containerized

The whole stack (ministack + the API) runs with Docker Compose.
The API is built from the multi-stage alpine [`api/Dockerfile`](api/Dockerfile)
(build context is the `api/` folder) and is capped at **512 MB RAM** and
**0.5 CPU**.

```bash
cd infra
docker compose up -d --build
```

This starts two containers:

| Service | Purpose | Host port |
|---------|---------|-----------|
| `ministack` | Emulates AWS Athena + S3 (DuckDB engine) | 4566 |
| `api` | FastAPI service | 8000 |

> **Note:** the API publishes host port `8000`. If a local dev server is already
> using it, stop that process first (or it will fail to bind).

Check it is up:

```bash
curl -s http://localhost:8000/health
curl -s "http://localhost:8000/vehicle-summary?manufacturer=BMW&model=X1&year=1999"
```

Useful commands:

```bash
docker compose logs -f api    # follow API logs
docker compose ps             # list running services
docker compose down           # stop everything
docker compose up -d --build api  # rebuild & restart only the API
```

## Run the API locally (without Docker)

### Install with UV

The project metadata (`pyproject.toml`, `uv.lock`, `.python-version`) now lives
in the [`api/`](api/) folder. Run uv from the repo root with `--project api`
so the `api.main` package stays importable:

```bash
uv sync --project api
```

### Run the API

```bash
uv run --project api uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Endpoints

```text
GET /health
GET /get_all
GET /athena?sql=...     # runs SQL via Athena (DuckDB engine)
```

Example:

```bash
curl --get http://localhost:8000/athena \
  --data-urlencode "sql=SELECT COUNT(*) AS n FROM read_parquet('s3://vehicle-data/parquet/manufacturers.parquet')"
```

### Optional environment variables

```text
AWS_ENDPOINT_URL=http://localhost:4566
AWS_REGION=us-east-1
VEHICLE_DATA_BUCKET=vehicle-data
VEHICLE_DATA_PREFIX=parquet/
ATHENA_OUTPUT_LOCATION=s3://athena-results/
ATHENA_TIMEOUT_SECONDS=30
```
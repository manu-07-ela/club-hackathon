#!/usr/bin/env bash
# Performance test runner for the /vehicle-summary endpoint, powered by Locust.
#
# Locust is the Python equivalent of Gatling — it gives you a live web UI with
# real-time response-time / RPS charts and can export a standalone HTML report.
#
# Usage:
#   ./run.sh            # headless: warmup + measured run, writes HTML + CSV report
#   ./run.sh web        # live web UI with Gatling-style charts (http://localhost:8089)
#
# Tunables (env vars, with defaults):
#   HOST=http://localhost:8000   target API base URL
#   USERS=1                      concurrent simulated users
#   SPAWN_RATE=1                 users started per second
#   WARMUP_SECONDS=5             warm-up window (discarded from the report)
#   RUN_SECONDS=60               measured window
#   TARGET_REQUESTS=100          requests to spread across the measured window

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# The uv project (pyproject.toml / uv.lock) now lives in the api/ folder.
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../api" && pwd)"

HOST="${HOST:-http://localhost:8000}"
USERS="${USERS:-1}"
SPAWN_RATE="${SPAWN_RATE:-1}"
export WARMUP_SECONDS="${WARMUP_SECONDS:-5}"
export RUN_SECONDS="${RUN_SECONDS:-60}"
export TARGET_REQUESTS="${TARGET_REQUESTS:-100}"

# Ministack / Athena results cleanup config. Every run starts from an empty
# results bucket so stale query outputs can never be reused (important once
# Athena result reuse is enabled).
AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://localhost:4566}"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
ATHENA_RESULTS_BUCKET="${ATHENA_RESULTS_BUCKET:-athena-results}"
SKIP_ATHENA_CLEAN="${SKIP_ATHENA_CLEAN:-0}"
export AWS_ENDPOINT_URL AWS_REGION AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY ATHENA_RESULTS_BUCKET

# Delete every object in the Athena results bucket so a fresh test never reuses
# cached/previous query results. Uses boto3 (already a project dependency) via
# uv, so no aws CLI install is required on the host.
clean_athena_results() {
  if [[ "$SKIP_ATHENA_CLEAN" == "1" ]]; then
    echo "Skipping Athena results cleanup (SKIP_ATHENA_CLEAN=1)."
    return 0
  fi
  echo "Cleaning Athena query results in s3://${ATHENA_RESULTS_BUCKET}/ (endpoint ${AWS_ENDPOINT_URL})"
  uv run --project "$PROJECT_DIR" python - <<'PY'
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

endpoint = os.environ["AWS_ENDPOINT_URL"]
bucket = os.environ["ATHENA_RESULTS_BUCKET"]

s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    region_name=os.environ["AWS_REGION"],
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)

try:
    paginator = s3.get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=bucket):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objs, "Quiet": True})
            deleted += len(objs)
    print(f"  removed {deleted} Athena result object(s) from s3://{bucket}/")
except ClientError as exc:
    code = exc.response.get("Error", {}).get("Code", "")
    if code in ("NoSuchBucket", "404"):
        print(f"  bucket s3://{bucket}/ does not exist yet; nothing to clean")
    else:
        print(f"  WARNING: could not clean s3://{bucket}/: {exc}", file=sys.stderr)
        sys.exit(1)
PY
}

# Total run time = warmup + measured window (warmup stats are reset away).
TOTAL_RUNTIME=$(python3 -c "print(int(float('${WARMUP_SECONDS}') + float('${RUN_SECONDS}')))")

MODE="${1:-headless}"

REPORT_DIR="$SCRIPT_DIR/reports"
mkdir -p "$REPORT_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [[ "$MODE" == "web" ]]; then
  clean_athena_results
  echo "Starting Locust web UI at http://localhost:8089 (target: $HOST)"
  echo "Set users=$USERS, run-time=${TOTAL_RUNTIME}s in the UI, then Start."
  exec uv run --project "$PROJECT_DIR" --with locust locust \
    -f locustfile.py \
    --host "$HOST"
fi

clean_athena_results

echo "Running headless load test against $HOST"
echo "  warmup=${WARMUP_SECONDS}s  measured=${RUN_SECONDS}s  target=${TARGET_REQUESTS} reqs  users=${USERS}"
echo "  total run-time=${TOTAL_RUNTIME}s"
echo

uv run --project "$PROJECT_DIR" --with locust locust \
  -f locustfile.py \
  --headless \
  --host "$HOST" \
  --users "$USERS" \
  --spawn-rate "$SPAWN_RATE" \
  --run-time "${TOTAL_RUNTIME}s" \
  --html "$REPORT_DIR/report_${STAMP}.html" \
  --csv "$REPORT_DIR/stats_${STAMP}" \
  --csv-full-history

echo
echo "HTML report: $REPORT_DIR/report_${STAMP}.html"
echo "CSV stats:   $REPORT_DIR/stats_${STAMP}_stats.csv"

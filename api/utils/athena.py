from __future__ import annotations

import os
import threading
import time

import boto3
from botocore.config import Config
from fastapi import HTTPException

_BOTO_CONFIG = Config(
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    max_pool_connections=int(os.getenv("AWS_MAX_POOL_CONNECTIONS", "16")),
    retries={"max_attempts": 3, "mode": "standard"},
)

_ATHENA_CONCURRENCY = int(os.getenv("ATHENA_MAX_CONCURRENCY", "6"))
_athena_semaphore = threading.Semaphore(_ATHENA_CONCURRENCY)


def _build_client(service: str):
    return boto3.client(
        service,
        endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        config=_BOTO_CONFIG,
    )


_s3_client = _build_client("s3")
_athena_client = _build_client("athena")


def get_s3_client():
    return _s3_client


def get_athena_client():
    return _athena_client


def run_athena_query(sql: str) -> list[dict]:
    athena = get_athena_client()
    output_location = os.getenv("ATHENA_OUTPUT_LOCATION", "s3://athena-results/")

    with _athena_semaphore:
        execution = athena.start_query_execution(
            QueryString=sql,
            ResultConfiguration={"OutputLocation": output_location},
        )
        query_id = execution["QueryExecutionId"]

        deadline = time.monotonic() + float(os.getenv("ATHENA_TIMEOUT_SECONDS", "30"))
        while True:
            status = athena.get_query_execution(QueryExecutionId=query_id)[
                "QueryExecution"
            ]["Status"]
            state = status["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            if time.monotonic() > deadline:
                raise HTTPException(status_code=504, detail="Athena query timed out")
            time.sleep(0.1)

        if state != "SUCCEEDED":
            reason = status.get("StateChangeReason", "Unknown error")
            raise HTTPException(
                status_code=400, detail=f"Athena query {state}: {reason}"
            )

        result = athena.get_query_results(QueryExecutionId=query_id)

    rows = result["ResultSet"]["Rows"]
    if not rows:
        return []

    columns = [col.get("VarCharValue") for col in rows[0]["Data"]]
    return [
        {columns[i]: cell.get("VarCharValue") for i, cell in enumerate(row["Data"])}
        for row in rows[1:]
    ]

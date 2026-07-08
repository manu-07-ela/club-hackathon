from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Query
from typing import Annotated
from functools import lru_cache

from api.middleware.timing import register_timing_middleware
from api.queries.vehicle_summary import build_vehicle_query
from api.utils.athena import run_athena_query
from api.utils.converters import to_bool, to_float, to_int

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


app = FastAPI(title="Vehicle Data API")
register_timing_middleware(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    run_athena_query("SELECT 1")
    return {"status": "ready"}


@lru_cache(maxsize=1024)
@app.get("/vehicle-summary")
def vehicle_summary(
    manufacturer: Annotated[str, Query(description="Manufacturer name, e.g. BMW.")],
    model: Annotated[str | None, Query(description="Model name, e.g. X1.")] = None,
    year: Annotated[int | None, Query(description="Model year, e.g. 1999.")] = None,
) -> dict[str, object]:
    bucket = os.getenv("VEHICLE_DATA_BUCKET", "vehicle-data")
    prefix = os.getenv("VEHICLE_DATA_PREFIX", "parquet/")

    sql = build_vehicle_query(bucket, prefix, manufacturer, model, year)
    rows = run_athena_query(sql)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No vehicle found for {manufacturer} {model} {year}",
        )

    row = rows[0]
    parts_raw = row.get("parts") or ""
    parts = [p for p in parts_raw.split("||") if p]

    return {
        "manufacturer": {
            "name": row.get("manufacturer_name"),
            "country": row.get("manufacturer_country"),
            "founded_year": to_int(row.get("founded_year")),
        },
        "model": {
            "name": row.get("model_name"),
            "segment": row.get("segment"),
            "msrp_usd": to_int(row.get("msrp_usd")),
        },
        "generation": {
            "name": row.get("generation_name"),
            "start_year": to_int(row.get("start_year")),
            "end_year": to_int(row.get("end_year")),
        },
        "recalls": {
            "open_recall": to_bool(row.get("open_recall")),
            "had_any_recall": (to_int(row.get("recall_count")) or 0) > 0,
            "recall_count": to_int(row.get("recall_count")) or 0,
        },
        "parts": parts,
        "consumers": {
            "total_owners": to_int(row.get("total_owners")) or 0,
            "top_country": row.get("top_country"),
        },
        "safety_rating": {
            "agency": row.get("rating_agency"),
            "overall_rating": to_float(row.get("overall_rating")),
            "crash_test_score": to_int(row.get("crash_test_score")),
        },
    }


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()

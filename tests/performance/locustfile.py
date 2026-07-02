"""Locust performance test for the /vehicle-summary endpoint.

Locust is the Python equivalent of Gatling: it ships a live web UI with
real-time response-time / throughput charts and can also export a standalone
HTML report (`--html`) plus CSV stats — the same kind of visualization Gatling
produces.

Load profile (all overridable via environment variables):

    WARMUP_SECONDS   warm-up window, default 5s. Requests sent during this
                     window are discarded from the final report so JIT, S3
                     clients, DuckDB caches etc. don't skew the numbers.
    RUN_SECONDS      measured window, default 60s.
    TARGET_REQUESTS  number of requests to spread across the measured window,
                     default 100 (=> ~1.67 req/s).

The total `--run-time` you pass to locust should be WARMUP_SECONDS + RUN_SECONDS
(65s by default). The bundled `run.sh` wires all of this up for you.

Run headless (generates HTML + CSV report):
    ./run.sh

Run with the live web UI (Gatling-style charts at http://localhost:8089):
    ./run.sh web
"""

from __future__ import annotations

import os
import random

import gevent
from locust import HttpUser, between, constant_throughput, events, task

# --------------------------------------------------------------------------- #
# Load profile configuration
# --------------------------------------------------------------------------- #
WARMUP_SECONDS = float(os.getenv("WARMUP_SECONDS", "5"))
RUN_SECONDS = float(os.getenv("RUN_SECONDS", "60"))
TARGET_REQUESTS = int(os.getenv("TARGET_REQUESTS", "100"))

# Per-user throughput so that, over the measured window, the configured number
# of requests is sent. With a single user this yields TARGET_REQUESTS spread
# evenly across RUN_SECONDS.
_THROUGHPUT_PER_SEC = TARGET_REQUESTS / RUN_SECONDS if RUN_SECONDS > 0 else 1.0

# Warm-up state. While this is set, users hit the lightweight `/ready` endpoint
# (a trivial `SELECT 1` Athena round-trip) instead of the heavy
# `/vehicle-summary` join. This primes JIT, boto3/S3 clients and DuckDB without
# exercising the real query path, then flips off once the measured window
# starts. Starts active only when there is a warm-up window to honour.
_warmup_active = WARMUP_SECONDS > 0

# --------------------------------------------------------------------------- #
# Query targets — verified joinable (manufacturer, model, year) tuples that all
# return HTTP 200 from /vehicle-summary. BMW X1 1999 is the deterministic
# anchor; the rest are real combinations sampled from the parquet data so the
# test exercises a variety of model_year_ids (different recall / part / owner
# branches), not just one hot row.
# --------------------------------------------------------------------------- #
TARGETS: list[tuple[str, str, int]] = [
    ("BMW", "X1", 1999),
    ("Maker_8867", "Model_14930", 2008),
    ("Maker_5517", "Model_41306", 2015),
    ("Maker_18795", "Model_92998", 2003),
    ("Maker_982", "Model_81534", 2005),
    ("Maker_13909", "Model_82872", 2024),
    ("Maker_4531", "Model_83584", 1998),
    ("Maker_9137", "Model_96309", 2019),
    ("Maker_3283", "Model_97879", 1995),
    ("Maker_7775", "Model_66653", 2021),
    ("Maker_6591", "Model_77898", 2010),
    ("Maker_5797", "Model_73965", 2006),
]

# --------------------------------------------------------------------------- #
# Correctness fixture for the deterministic anchor. BMW X1 1999 always resolves
# to the same row, so we can assert the full response payload exactly. Any drift
# here means the optimization changed the *meaning* of the data, not just its
# speed — which must fail the load test.
# --------------------------------------------------------------------------- #
EXPECTED_BMW_X1_1999: dict = {
    "manufacturer": {"name": "BMW", "country": "Germany", "founded_year": 1916},
    "model": {"name": "X1", "segment": "SUV", "msrp_usd": 38000},
    "generation": {"name": "F48", "start_year": 1995, "end_year": 2010},
    "recalls": {"open_recall": True, "had_any_recall": True, "recall_count": 8},
    "parts": [
        "Engine Block",
        "Turbocharger",
        "ABS Module",
        "Part_14599",
        "Part_38591",
        "Part_49811",
        "Part_59807",
        "Part_60328",
        "Part_60372",
        "Part_72085",
        "Part_83709",
        "Part_95817",
        "Part_96706",
        "Part_134539",
        "Part_137310",
        "Part_150204",
        "Part_160682",
        "Part_190847",
        "Part_193558",
    ],
    "consumers": {"total_owners": 15, "top_country": "USA"},
    "safety_rating": {"agency": "NHTSA", "overall_rating": 4.8, "crash_test_score": 93},
}


def _validate_summary(
    body: dict, manufacturer: str, model: str, year: int
) -> str | None:
    """Check that a /vehicle-summary payload is internally consistent and makes
    sense. Returns ``None`` when the response is sound, otherwise a short string
    describing the first problem found (used as the Locust failure message).
    """
    # Exact-match the deterministic anchor against the known fixture.
    if (manufacturer, model, year) == ("BMW", "X1", 1999):
        if body != EXPECTED_BMW_X1_1999:
            return "BMW X1 1999 payload does not match expected fixture"
        return None

    # --- shape: every top-level section must be present -------------------- #
    for section in (
        "manufacturer",
        "model",
        "generation",
        "recalls",
        "parts",
        "consumers",
        "safety_rating",
    ):
        if section not in body:
            return f"Missing section '{section}'"

    man = body["manufacturer"]
    mod = body["model"]
    gen = body["generation"]
    rec = body["recalls"]
    parts = body["parts"]
    cons = body["consumers"]
    safety = body["safety_rating"]

    # --- manufacturer / model: must echo what was requested ---------------- #
    if man.get("name") != manufacturer:
        return f"manufacturer.name={man.get('name')!r} != requested {manufacturer!r}"
    if not man.get("country"):
        return "manufacturer.country is empty"
    founded = man.get("founded_year")
    if not isinstance(founded, int) or not (1800 <= founded <= 2100):
        return f"manufacturer.founded_year out of range: {founded!r}"

    if mod.get("name") != model:
        return f"model.name={mod.get('name')!r} != requested {model!r}"
    if not mod.get("segment"):
        return "model.segment is empty"
    msrp = mod.get("msrp_usd")
    if not isinstance(msrp, int) or msrp <= 0:
        return f"model.msrp_usd not a positive int: {msrp!r}"

    # --- generation: requested year must fall inside the generation span --- #
    start, end = gen.get("start_year"), gen.get("end_year")
    if start is not None and end is not None:
        if not (isinstance(start, int) and isinstance(end, int)):
            return f"generation years not ints: {start!r}/{end!r}"
        if start > end:
            return f"generation.start_year {start} > end_year {end}"
        if not (start <= year <= end):
            return f"requested year {year} outside generation {start}-{end}"

    # --- recalls: counters must be consistent with each other -------------- #
    count = rec.get("recall_count")
    if not isinstance(count, int) or count < 0:
        return f"recalls.recall_count invalid: {count!r}"
    if not isinstance(rec.get("open_recall"), bool):
        return "recalls.open_recall is not a bool"
    if rec.get("had_any_recall") != (count > 0):
        return f"recalls.had_any_recall inconsistent with recall_count={count}"
    if count == 0 and rec.get("open_recall") is True:
        return "open_recall=True but recall_count=0"

    # --- parts: list of non-empty strings ---------------------------------- #
    if not isinstance(parts, list):
        return "parts is not a list"
    if any(not isinstance(p, str) or not p for p in parts):
        return "parts contains an empty/non-string entry"

    # --- consumers: owner count vs top_country must agree ------------------ #
    owners = cons.get("total_owners")
    if not isinstance(owners, int) or owners < 0:
        return f"consumers.total_owners invalid: {owners!r}"
    if owners > 0 and not cons.get("top_country"):
        return "total_owners>0 but top_country is empty"

    # --- safety rating: optional, but ranges must be sane when present ------ #
    overall = safety.get("overall_rating")
    if overall is not None and not (0.0 <= float(overall) <= 5.0):
        return f"safety_rating.overall_rating out of [0,5]: {overall!r}"
    crash = safety.get("crash_test_score")
    if crash is not None and not (0 <= int(crash) <= 100):
        return f"safety_rating.crash_test_score out of [0,100]: {crash!r}"

    return None


class VehicleSummaryUser(HttpUser):
    """Simulates a client hitting the heavy 10-table join endpoint."""

    # constant_throughput caps each user at N task iterations per second, which
    # is how we shape "TARGET_REQUESTS over RUN_SECONDS". Fallback to a small
    # wait if throughput shaping is disabled.
    if _THROUGHPUT_PER_SEC > 0:
        wait_time = constant_throughput(_THROUGHPUT_PER_SEC)
    else:
        wait_time = between(0.5, 1.0)

    @task
    def vehicle_summary(self) -> None:
        # During the warm-up window, only send cheap readiness probes so the
        # heavy join path is never exercised until measurement begins.
        if _warmup_active:
            self._ready_probe()
            return
        manufacturer, model, year = random.choice(TARGETS)
        with self.client.get(
            "/vehicle-summary",
            params={"manufacturer": manufacturer, "model": model, "year": year},
            name="/vehicle-summary",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"HTTP {response.status_code} for "
                    f"{manufacturer} {model} {year}"
                )
                return
            try:
                body = response.json()
            except ValueError:
                response.failure("Response body is not valid JSON")
                return
            problem = _validate_summary(body, manufacturer, model, year)
            if problem is not None:
                response.failure(
                    f"Invalid result for {manufacturer} {model} {year}: {problem}"
                )

    def _ready_probe(self) -> None:
        """Warm-up request: hit the lightweight `/ready` endpoint instead of the
        real query. Stats from this window are discarded after warm-up."""
        with self.client.get(
            "/ready",
            name="/ready (warmup)",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code} on /ready warmup")


# --------------------------------------------------------------------------- #
# Warm-up handling: discard everything sent during the warm-up window so the
# final report only reflects the steady-state measured window.
# --------------------------------------------------------------------------- #
@events.test_start.add_listener
def _on_test_start(environment, **_kwargs) -> None:
    if WARMUP_SECONDS <= 0:
        return

    def _reset_after_warmup() -> None:
        global _warmup_active
        gevent.sleep(WARMUP_SECONDS)
        # Switch users over to the real /vehicle-summary path and drop the
        # readiness-probe stats collected during warm-up.
        _warmup_active = False
        runner = environment.runner
        if runner is not None:
            runner.stats.reset_all()
        print(
            f"[warmup] {WARMUP_SECONDS:.0f}s warm-up complete (/ready probes) — "
            f"stats reset; measuring /vehicle-summary for {RUN_SECONDS:.0f}s "
            f"(~{TARGET_REQUESTS} requests target)."
        )

    gevent.spawn(_reset_after_warmup)

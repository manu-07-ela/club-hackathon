from __future__ import annotations


def _sql_str(value: str) -> str:
    """Escape a string literal for safe inclusion in a SQL query."""
    return "'" + value.replace("'", "''") + "'"


def _t(bucket: str, prefix: str, table: str) -> str:
    """Build a read_parquet() reference to a table's parquet file."""
    return f"read_parquet('s3://{bucket}/{prefix}{table}.parquet')"


# ---------------------------------------------------------------------------
# Manufacturer
# ---------------------------------------------------------------------------


def build_manufacturer_sql(
    bucket: str,
    prefix: str,
    manufacturer: str,
) -> str:
    """Return manufacturer information."""

    manufacturers = _t(bucket, prefix, "manufacturers")

    return f"""
SELECT
    manufacturer_id,
    name AS manufacturer_name,
    country AS manufacturer_country,
    founded_year
FROM {manufacturers}
WHERE name = {_sql_str(manufacturer)}
LIMIT 1
""".strip()


# ---------------------------------------------------------------------------
# Manufacturer + Model
# ---------------------------------------------------------------------------


def build_model_sql(
    bucket: str,
    prefix: str,
    manufacturer: str,
    model: str,
) -> str:
    """Return manufacturer and model information."""

    manufacturers = _t(bucket, prefix, "manufacturers")
    models = _t(bucket, prefix, "models")

    return f"""
SELECT
    m.manufacturer_id,
    m.name AS manufacturer_name,
    m.country AS manufacturer_country,
    m.founded_year,
    md.model_id,
    md.name AS model_name,
    md.segment
FROM {manufacturers} m
JOIN {models} md
    ON md.manufacturer_id = m.manufacturer_id
WHERE
    m.name = {_sql_str(manufacturer)}
    AND md.name = {_sql_str(model)}
LIMIT 1
""".strip()


# ---------------------------------------------------------------------------
# Manufacturer + Model + Year (Full Vehicle Summary)
# ---------------------------------------------------------------------------


def build_vehicle_summary_sql(
    bucket: str,
    prefix: str,
    manufacturer: str,
    model: str,
    year: int,
) -> str:
    """Return the complete vehicle summary."""

    manu = _sql_str(manufacturer)
    mod = _sql_str(model)

    manufacturers = _t(bucket, prefix, "manufacturers")
    models = _t(bucket, prefix, "models")
    model_years = _t(bucket, prefix, "model_years")
    generations = _t(bucket, prefix, "generations")
    recalls = _t(bucket, prefix, "recalls")
    parts = _t(bucket, prefix, "parts")
    model_parts = _t(bucket, prefix, "model_parts")
    consumers = _t(bucket, prefix, "consumers")
    consumer_vehicles = _t(bucket, prefix, "consumer_vehicles")
    safety_ratings = _t(bucket, prefix, "safety_ratings")

    return f"""
WITH base AS (
    SELECT
        m.manufacturer_id,
        m.name AS manufacturer_name,
        m.country AS manufacturer_country,
        m.founded_year,
        md.model_id,
        md.name AS model_name,
        md.segment,
        my.model_year_id,
        my.year,
        my.msrp_usd
    FROM {manufacturers} m
    JOIN {models} md
        ON md.manufacturer_id = m.manufacturer_id
    JOIN {model_years} my
        ON my.model_id = md.model_id
    WHERE
        m.name = {manu}
        AND md.name = {mod}
        AND my.year = {year}
    LIMIT 1
),
gen AS (
    SELECT
        g.model_id,
        g.generation_name,
        g.start_year,
        g.end_year
    FROM {generations} g
    JOIN base
        ON base.model_id = g.model_id
    WHERE {year} BETWEEN g.start_year AND g.end_year
    ORDER BY g.start_year
    LIMIT 1
),
rec AS (
    SELECT
        r.model_year_id,
        COUNT(*) AS recall_count,
        BOOL_OR(NOT r.resolved) AS open_recall
    FROM {recalls} r
    JOIN base
        ON base.model_year_id = r.model_year_id
    GROUP BY r.model_year_id
),
prt AS (
    SELECT
        mp.model_year_id,
        STRING_AGG(
            p.part_name,
            '||'
            ORDER BY p.part_id
        ) AS parts
    FROM {model_parts} mp
    JOIN {parts} p
        ON p.part_id = mp.part_id
    JOIN base
        ON base.model_year_id = mp.model_year_id
    GROUP BY mp.model_year_id
),
owners AS (
    SELECT
        cv.model_year_id,
        c.country
    FROM {consumer_vehicles} cv
    JOIN {consumers} c
        ON c.consumer_id = cv.consumer_id
    JOIN base
        ON base.model_year_id = cv.model_year_id
),
cons AS (
    SELECT
        COUNT(*) AS total_owners,
        (
            SELECT country
            FROM owners
            GROUP BY country
            ORDER BY COUNT(*) DESC, country
            LIMIT 1
        ) AS top_country
    FROM owners
),
sr AS (
    SELECT
        s.model_year_id,
        s.rating_agency,
        s.overall_rating,
        s.crash_test_score
    FROM {safety_ratings} s
    JOIN base
        ON base.model_year_id = s.model_year_id
    ORDER BY s.overall_rating DESC
    LIMIT 1
)
SELECT
    base.manufacturer_name,
    base.manufacturer_country,
    base.founded_year,
    base.model_name,
    base.segment,
    base.msrp_usd,
    gen.generation_name,
    gen.start_year,
    gen.end_year,
    COALESCE(rec.recall_count, 0) AS recall_count,
    COALESCE(rec.open_recall, FALSE) AS open_recall,
    prt.parts,
    COALESCE(cons.total_owners, 0) AS total_owners,
    cons.top_country,
    sr.rating_agency,
    sr.overall_rating,
    sr.crash_test_score
FROM base
LEFT JOIN gen
    ON gen.model_id = base.model_id
LEFT JOIN rec
    ON rec.model_year_id = base.model_year_id
LEFT JOIN prt
    ON prt.model_year_id = base.model_year_id
LEFT JOIN cons
    ON TRUE
LEFT JOIN sr
    ON sr.model_year_id = base.model_year_id
""".strip()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_vehicle_query(
    bucket: str,
    prefix: str,
    manufacturer: str,
    model: str | None = None,
    year: int | None = None,
) -> str:
    """
    Build the appropriate query based on the information provided.

    manufacturer                  -> manufacturers
    manufacturer + model          -> manufacturers + models
    manufacturer + model + year   -> full vehicle summary
    """

    if model is None:
        return build_manufacturer_sql(
            bucket=bucket,
            prefix=prefix,
            manufacturer=manufacturer,
        )

    if year is None:
        return build_model_sql(
            bucket=bucket,
            prefix=prefix,
            manufacturer=manufacturer,
            model=model,
        )

    return build_vehicle_summary_sql(
        bucket=bucket,
        prefix=prefix,
        manufacturer=manufacturer,
        model=model,
        year=year,
    )

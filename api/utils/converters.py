from __future__ import annotations


def to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(float(str(value)))


def to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(str(value))


def to_bool(value: object) -> bool:
    return str(value).strip().lower() in ("true", "1", "t")

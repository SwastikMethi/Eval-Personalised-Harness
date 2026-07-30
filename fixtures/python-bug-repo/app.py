"""Tiny fixture app with a seeded bug: median() mishandles even-length lists."""


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("empty")
    ordered = sorted(values)
    # BUG: even-length lists should average the two middle values.
    return ordered[len(ordered) // 2]

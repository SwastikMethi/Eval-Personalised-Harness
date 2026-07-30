from app import median


def test_median_odd() -> None:
    assert median([3, 1, 2]) == 2

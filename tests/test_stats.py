import pytest

from netlag.bufferbloat import BufferbloatError, evaluate, grade_bufferbloat
from netlag.stats import Sample, jitter, percentile, summarize


def test_percentile_interpolates() -> None:
    values = [1, 2, 3, 4, 5]
    assert percentile(values, 0) == 1
    assert percentile(values, 50) == 3
    assert percentile(values, 100) == 5
    assert percentile(values, 25) == 2
    assert percentile([10, 20], 50) == 15


def test_percentile_high_quantiles() -> None:
    values = list(range(1, 101))
    assert percentile(values, 95) == pytest.approx(95.05)
    assert percentile(values, 99) == pytest.approx(99.01)


def test_percentile_is_order_independent() -> None:
    assert percentile([5, 1, 3, 2, 4], 50) == 3


@pytest.mark.parametrize("bad", [-1, 101])
def test_percentile_rejects_out_of_range(bad: float) -> None:
    with pytest.raises(ValueError):
        percentile([1, 2], bad)


def test_percentile_rejects_empty() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)


def test_jitter_mean_absolute_difference() -> None:
    assert jitter([10, 20, 10, 20]) == 10
    assert jitter([10, 12, 11]) == pytest.approx(1.5)


def test_jitter_constant_and_short() -> None:
    assert jitter([15, 15, 15]) == 0
    assert jitter([15]) == 0
    assert jitter([]) == 0


def test_summarize_with_loss() -> None:
    stats = summarize([10, None, 20, 30, None])
    assert stats.sent == 5
    assert stats.received == 3
    assert stats.loss_pct == pytest.approx(40)
    assert (stats.min, stats.avg, stats.max) == (10, 20, 30)
    assert stats.p50 == 20
    assert stats.jitter == 10


def test_summarize_all_lost() -> None:
    stats = summarize([None, None])
    assert stats.loss_pct == 100
    assert stats.avg is None
    assert stats.p99 is None
    assert stats.jitter == 0


def test_summarize_empty() -> None:
    stats = summarize([])
    assert stats.sent == 0
    assert stats.loss_pct == 0


@pytest.mark.parametrize(
    ("delta", "grade"),
    [
        (-5, "A"),
        (0, "A"),
        (14.9, "A"),
        (15, "B"),
        (29, "B"),
        (30, "C"),
        (59, "C"),
        (60, "D"),
        (119, "D"),
        (120, "E"),
        (199, "E"),
        (200, "F"),
        (900, "F"),
    ],
)
def test_grade_bufferbloat(delta: float, grade: str) -> None:
    assert grade_bufferbloat(delta) == grade


def test_evaluate_builds_result() -> None:
    result = evaluate([10, 10, 10], [60, 80, 70], 25_000_000, 10)
    assert result.delta_ms == pytest.approx(60)
    assert result.grade == "D"
    assert result.mbps == pytest.approx(20)


@pytest.mark.parametrize(
    ("idle", "loaded", "size"),
    [
        ([None, None], [50], 1000),
        ([10], [50], 0),
        ([10], [None, None], 1000),
    ],
)
def test_evaluate_inconclusive(idle: list[Sample], loaded: list[Sample], size: int) -> None:
    with pytest.raises(BufferbloatError):
        evaluate(idle, loaded, size, 10)

"""Reliability aggregation + ranking + recommendations (spec §16-§17).

Default weights: correctness 50 / reliability 20 / execution efficiency 15 /
token efficiency 10 / resource efficiency 5. Efficiency is normalized within
the task cohort — a documented caveat: scores are cohort-relative, adding a
bad combination shifts everyone's efficiency normalization (eng review
Tension 5). At the default 3 repetitions results are flagged statistically
weak; no significance claims are made.
"""

import statistics
from dataclasses import dataclass, field
from typing import Any

DEFAULT_WEIGHTS = {
    "correctness": 0.50,
    "reliability": 0.20,
    "execution_efficiency": 0.15,
    "token_efficiency": 0.10,
    "resource_efficiency": 0.05,
}

MIN_REPS_FOR_CONFIDENCE = 3


@dataclass
class RunSample:
    combination_id: str
    harness: str
    model_id: str
    task_id: str
    state: str  # terminal RunState value
    score: float | None  # evaluation score 0..1, None if not evaluated
    signal: str | None
    duration_s: float | None
    total_tokens: int | None
    patch_produced: bool


@dataclass
class CombinationStats:
    combination_id: str
    harness: str
    model_id: str
    task_id: str
    runs: int = 0
    completed: int = 0
    success_rate: float = 0.0
    mean_score: float | None = None
    median_score: float | None = None
    stdev_score: float | None = None
    timeout_rate: float = 0.0
    empty_patch_rate: float = 0.0
    crash_rate: float = 0.0
    mean_duration_s: float | None = None
    mean_tokens: float | None = None
    insufficient_signal: bool = False
    eligible: bool = True
    ineligible_reasons: list[str] = field(default_factory=list)
    statistically_weak: bool = True
    weighted_score: float | None = None
    components: dict[str, float] = field(default_factory=dict)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate_combination(samples: list[RunSample]) -> CombinationStats:
    first = samples[0]
    stats = CombinationStats(
        combination_id=first.combination_id,
        harness=first.harness,
        model_id=first.model_id,
        task_id=first.task_id,
        runs=len(samples),
    )
    scores = [s.score for s in samples if s.score is not None]
    stats.completed = sum(1 for s in samples if s.state == "COMPLETED")
    stats.success_rate = (
        sum(1 for s in samples if s.state == "COMPLETED" and (s.score or 0) >= 0.5)
        / len(samples)
    )
    stats.mean_score = _mean(scores)
    stats.median_score = statistics.median(scores) if scores else None
    stats.stdev_score = statistics.stdev(scores) if len(scores) >= 2 else None
    stats.timeout_rate = sum(1 for s in samples if s.state == "TIMED_OUT") / len(samples)
    stats.empty_patch_rate = sum(1 for s in samples if not s.patch_produced) / len(samples)
    stats.crash_rate = sum(1 for s in samples if s.state == "FAILED") / len(samples)
    stats.mean_duration_s = _mean([s.duration_s for s in samples if s.duration_s is not None])
    stats.mean_tokens = _mean([float(s.total_tokens) for s in samples if s.total_tokens])
    stats.insufficient_signal = any(
        s.signal == "INSUFFICIENT_EVALUATION_SIGNAL" for s in samples
    )
    stats.statistically_weak = stats.completed < MIN_REPS_FOR_CONFIDENCE

    # Eligibility rules (spec §17)
    if all(not s.patch_produced for s in samples):
        stats.ineligible_reasons.append("never produces a patch")
    if stats.timeout_rate > 0.5:
        stats.ineligible_reasons.append("more than half of runs time out")
    if stats.insufficient_signal:
        stats.ineligible_reasons.append("evaluation signal insufficient")
    if stats.completed == 0:
        stats.ineligible_reasons.append("no completed repetitions")
    stats.eligible = not stats.ineligible_reasons
    return stats


def _normalize_lower_is_better(value: float | None, cohort: list[float]) -> float:
    """0..1 within task cohort; missing value scores 0 (never rewarded)."""
    if value is None or not cohort:
        return 0.0
    lo, hi = min(cohort), max(cohort)
    if hi == lo:
        return 1.0
    return 1.0 - (value - lo) / (hi - lo)


def score_combinations(
    all_stats: list[CombinationStats], weights: dict[str, float] | None = None
) -> None:
    """Fill weighted_score in place. Efficiency normalized per task cohort.

    A combination that stops early WITHOUT completing the task gets no
    efficiency reward: correctness gates the efficiency terms.
    """
    weights = weights or DEFAULT_WEIGHTS
    by_task: dict[str, list[CombinationStats]] = {}
    for stat in all_stats:
        by_task.setdefault(stat.task_id, []).append(stat)

    for cohort in by_task.values():
        durations = [c.mean_duration_s for c in cohort if c.mean_duration_s is not None]
        tokens = [c.mean_tokens for c in cohort if c.mean_tokens is not None]
        for stat in cohort:
            if not stat.eligible:
                stat.weighted_score = None
                continue
            correctness = stat.mean_score or 0.0
            reliability = 1.0 - min(
                stat.crash_rate + stat.timeout_rate + (stat.stdev_score or 0.0), 1.0
            )
            exec_eff = _normalize_lower_is_better(stat.mean_duration_s, durations)
            token_eff = _normalize_lower_is_better(stat.mean_tokens, tokens)
            gate = correctness  # early-exit without solving earns nothing
            stat.components = {
                "correctness": correctness,
                "reliability": reliability,
                "execution_efficiency": exec_eff * gate,
                "token_efficiency": token_eff * gate,
                "resource_efficiency": exec_eff * gate,
            }
            stat.weighted_score = sum(
                weights[k] * v for k, v in stat.components.items()
            )


def pareto_frontier(
    points: list[tuple[str, float, float]],
) -> list[str]:
    """IDs on the frontier of (maximize correctness, minimize cost axis)."""
    frontier = []
    for cid, correctness, cost in points:
        dominated = any(
            other_corr >= correctness and other_cost <= cost and (oc != cid)
            for oc, other_corr, other_cost in points
            if not (other_corr == correctness and other_cost == cost)
        )
        if not dominated:
            frontier.append(cid)
    return frontier


def recommend(all_stats: list[CombinationStats]) -> dict[str, Any]:
    """Best quality / reliability / efficiency / balanced (spec §17)."""

    def _by_combo(stats_list: list[CombinationStats]) -> dict[str, dict[str, Any]]:
        # collapse per-task stats to per (harness, model) means
        groups: dict[str, list[CombinationStats]] = {}
        for stat in stats_list:
            groups.setdefault(f"{stat.harness}|{stat.model_id}", []).append(stat)
        out = {}
        for key, group in groups.items():
            eligible = [g for g in group if g.eligible and g.weighted_score is not None]
            if not eligible:
                continue
            out[key] = {
                "harness": group[0].harness,
                "model_id": group[0].model_id,
                "tasks": len(group),
                "completed_reps": sum(g.completed for g in group),
                "correctness": _mean([g.mean_score or 0.0 for g in eligible]) or 0.0,
                "reliability": _mean(
                    [g.components.get("reliability", 0.0) for g in eligible]
                )
                or 0.0,
                "efficiency": _mean(
                    [g.components.get("execution_efficiency", 0.0) for g in eligible]
                )
                or 0.0,
                "balanced": _mean([g.weighted_score or 0.0 for g in eligible]) or 0.0,
                "avg_duration_s": _mean(
                    [g.mean_duration_s for g in eligible if g.mean_duration_s is not None]
                ),
                "avg_tokens": _mean(
                    [g.mean_tokens for g in eligible if g.mean_tokens is not None]
                ),
                "failure_rate": _mean([g.crash_rate + g.timeout_rate for g in eligible])
                or 0.0,
                "statistically_weak": any(g.statistically_weak for g in eligible),
            }
        return out

    combos = _by_combo(all_stats)
    if not combos:
        return {"recommendations": {}, "note": "no eligible combinations"}

    def _best(metric: str) -> dict[str, Any]:
        key = max(combos, key=lambda k: combos[k][metric])
        entry = dict(combos[key])
        entry["why"] = f"highest {metric} among eligible combinations"
        return entry

    return {
        "recommendations": {
            "best_quality": _best("correctness"),
            "best_reliability": _best("reliability"),
            "best_efficiency": _best("efficiency"),
            "best_balanced": _best("balanced"),
        },
        "combinations": combos,
    }

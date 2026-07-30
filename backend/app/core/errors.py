"""Single failure taxonomy (eng review 5A).

Provider, harness, queue, and telemetry all map their native errors into
ErrorCategory so reliability stats and failure-breakdown charts aggregate
one vocabulary (spec §16).
"""

from enum import StrEnum


class ErrorCategory(StrEnum):
    NONE = "none"
    MODEL_PROVIDER = "model_provider"  # 5xx, invalid response
    RATE_LIMITED = "rate_limited"  # 429 / 402
    CONTEXT_LIMIT = "context_limit"
    TIMEOUT = "timeout"
    HARNESS = "harness"  # harness crash / protocol error
    SETUP = "setup"  # repo/sandbox/dependency failure
    EVALUATION = "evaluation"  # evaluator itself failed
    WRONG_SOLUTION = "wrong_solution"  # agent finished, output incorrect
    BUDGET_EXCEEDED = "budget_exceeded"
    CRASH = "crash"  # backend died mid-run (reconciliation)
    CANCELLED = "cancelled"


def category_from_http_status(status: int) -> ErrorCategory:
    if status in (402, 429):
        return ErrorCategory.RATE_LIMITED
    if status >= 500:
        return ErrorCategory.MODEL_PROVIDER
    return ErrorCategory.MODEL_PROVIDER

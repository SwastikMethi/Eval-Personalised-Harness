from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import (
    BaselineResult,
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    ExperimentCombination,
    Repository,
    RepositoryCommand,
    RunEvent,
)
from app.models.core import RunState

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ready"}


class RepositoryIn(BaseModel):
    name: str
    source: str  # local | github
    path_or_url: str


@router.post("/repositories")
def create_repository(
    body: RepositoryIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    repo = Repository(name=body.name, source=body.source, path_or_url=body.path_or_url)
    session.add(repo)
    session.commit()
    return {"id": repo.id}


@router.get("/repositories")
def list_repositories(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    repos = session.scalars(select(Repository)).all()
    return [
        {"id": r.id, "name": r.name, "source": r.source, "path_or_url": r.path_or_url}
        for r in repos
    ]


class TaskIn(BaseModel):
    repository_id: str
    kind: str = "user_defined"
    title: str
    prompt: str


@router.post("/tasks")
def create_task(body: TaskIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    if session.get(Repository, body.repository_id) is None:
        raise HTTPException(404, "repository not found")
    task = BenchmarkTask(
        repository_id=body.repository_id, kind=body.kind, title=body.title, prompt=body.prompt
    )
    session.add(task)
    session.commit()
    return {"id": task.id}


class CombinationIn(BaseModel):
    harness: str
    provider: str
    model_id: str


class ExperimentIn(BaseModel):
    repository_id: str
    name: str
    task_ids: list[str]
    combinations: list[CombinationIn]
    repetitions: int = 3
    config: dict[str, Any] = {}


def derive_config(session: Session, repository_id: str) -> dict[str, Any]:
    """Config the runs actually need, taken from persisted analysis.

    Without this, `queue._evaluate` falls back to a hardcoded `pytest -v` and
    an empty baseline — so a JS repo would be graded with pytest and every
    regression check would compare against nothing.
    """
    derived: dict[str, Any] = {}

    commands = session.scalars(
        select(RepositoryCommand).where(RepositoryCommand.repository_id == repository_id)
    ).first()
    if commands is not None:
        named = {
            "install": commands.install,
            "build": commands.build,
            "test": commands.test,
            "lint": commands.lint,
            "typecheck": commands.typecheck,
        }
        derived["commands"] = {k: v for k, v in named.items() if v}
        if commands.test_framework:
            derived["test_framework"] = commands.test_framework

    baseline = session.scalars(
        select(BaselineResult)
        .where(BaselineResult.repository_id == repository_id)
        .order_by(BaselineResult.created_at.desc())
    ).first()
    if baseline is not None:
        # Pre-existing failures are never counted as agent regressions (spec §7).
        derived["baseline_cases"] = baseline.test_cases

    return derived


@router.get("/harnesses")
def list_available_harnesses() -> list[dict[str, Any]]:
    """Harnesses registered in THIS process — the UI must not hardcode them.

    `sandboxed` matters to the user: those need Docker and get a container plus
    a run-scoped proxy token; the fake runs in-process for zero-cost demos.
    """
    from app.harnesses.base import list_harnesses
    from app.orchestration.queue import SANDBOXED_HARNESSES

    return [
        {"name": name, "sandboxed": name in SANDBOXED_HARNESSES}
        for name in list_harnesses()
    ]


class PreviewIn(BaseModel):
    task_ids: list[str]
    harnesses: list[str]
    model_ids: list[str]
    repetitions: int = 3


@router.post("/experiments/preview")
def preview_matrix(body: PreviewIn) -> dict[str, Any]:
    """Expanded run count before committing (spec §13: show expected runs).

    Also reports the model-request ceiling, because on a free tier the
    binding constraint is requests per day, not wall-clock.
    """
    combos = len(body.harnesses) * len(body.model_ids)
    runs = combos * len(body.task_ids) * body.repetitions
    return {
        "harnesses": len(body.harnesses),
        "models": len(body.model_ids),
        "tasks": len(body.task_ids),
        "repetitions": body.repetitions,
        "combinations": combos,
        "runs": runs,
        "expression": (
            f"{len(body.harnesses)} harnesses × {len(body.model_ids)} models × "
            f"{len(body.task_ids)} tasks × {body.repetitions} reps = {runs} runs"
        ),
    }


@router.post("/experiments")
async def create_experiment(
    body: ExperimentIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    if session.get(Repository, body.repository_id) is None:
        raise HTTPException(404, "repository not found")

    # Preflight (spec §21): prove every model can actually be called before
    # writing any runs. A provider's catalog is not an entitlement list —
    # deepseek-coder listed fine and then 404'd on its first request, after a
    # workspace, an image, a container and a seal had all been paid for.
    from app.api.proxy import provider_for
    from app.providers import preflight

    probes = await preflight.check_combinations(body.combinations, provider_for)
    if unusable := [p for p in probes if not p.ok]:
        # Refuse the whole experiment rather than queue a matrix with holes:
        # a partially-created experiment that dies on cell 3 is harder to
        # reason about than one that was never created.
        raise HTTPException(
            422,
            {
                "message": "these model(s) cannot be used and no runs were created",
                "unusable": [{"combination": p.label, "reason": p.detail} for p in unusable],
            },
        )
    # Explicit request values win over derived ones so a caller can override.
    config = {**derive_config(session, body.repository_id), **body.config}
    exp = Experiment(
        repository_id=body.repository_id,
        name=body.name,
        repetitions=body.repetitions,
        config=config,
    )
    session.add(exp)
    session.flush()
    run_count = 0
    for task_id in body.task_ids:
        if session.get(BenchmarkTask, task_id) is None:
            raise HTTPException(404, f"task not found: {task_id}")
        for combo_in in body.combinations:
            combo = ExperimentCombination(
                experiment_id=exp.id,
                task_id=task_id,
                harness=combo_in.harness,
                provider=combo_in.provider,
                model_id=combo_in.model_id,
            )
            session.add(combo)
            session.flush()
            for rep in range(1, body.repetitions + 1):
                session.add(
                    BenchmarkRun(
                        combination_id=combo.id,
                        repetition=rep,
                        state=RunState.PENDING,
                        idempotency_key=f"{combo.id}:{rep}",
                    )
                )
                run_count += 1
    exp.status = "running"
    session.commit()
    return {"id": exp.id, "runs": run_count}


@router.get("/experiments/{experiment_id}")
def get_experiment(
    experiment_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    combos = session.scalars(
        select(ExperimentCombination).where(ExperimentCombination.experiment_id == exp.id)
    ).all()
    combo_ids = [c.id for c in combos]
    runs = (
        session.scalars(
            select(BenchmarkRun).where(BenchmarkRun.combination_id.in_(combo_ids))
        ).all()
        if combo_ids
        else []
    )
    states = [r.state for r in runs]
    return {
        "id": exp.id,
        "name": exp.name,
        "status": exp.status,
        "runs": {
            "total": len(runs),
            "by_state": {s: states.count(s) for s in sorted(set(states))},
        },
    }


@router.get("/experiments")
def list_experiments(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    exps = session.scalars(select(Experiment)).all()
    return [{"id": e.id, "name": e.name, "status": e.status} for e in exps]


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    events = session.scalars(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.created_at)
    ).all()
    return {
        "id": run.id,
        "state": run.state,
        "repetition": run.repetition,
        "error_category": run.error_category,
        "error_message": run.error_message,
        "result": run.result,
        "events": [{"type": e.event_type, "payload": e.payload} for e in events],
    }

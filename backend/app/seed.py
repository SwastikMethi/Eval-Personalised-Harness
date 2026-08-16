"""`make seed`: create the demo repository, analysis, tasks, and an example
experiment configuration (spec §22).

Idempotent — re-running updates the existing rows rather than duplicating
them, so it is safe to run against a database that already has data.

This seeds *configuration* only; it queues nothing and spends no model quota.
Use `make demo` to actually execute an experiment with fakes.
"""

import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import SessionLocal, ensure_schema
from app.models import (
    BenchmarkTask,
    Experiment,
    Repository,
    RepositoryAnalysis,
    RepositoryCommand,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "python-bug-repo"

# Pinned in vault/05-decisions/ADR-002 Model Selection.md. All free variants;
# the exact ids matter — never substitute a model silently (spec §4).
MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openai/gpt-oss-20b:free",
    "cohere/north-mini-code:free",
]
HARNESSES = ["mini-swe-agent", "smolagents"]

TASKS = [
    (
        "Fix median() for even-length lists",
        "median() returns the wrong value for even-length lists. "
        "Fix it so it returns the mean of the two middle elements.",
    ),
    (
        "Add input validation to median()",
        "median() should raise a clear ValueError when given an empty list "
        "instead of failing with an IndexError.",
    ),
]


def _repository(session: Session) -> Repository:
    repo = session.scalars(
        select(Repository).where(Repository.path_or_url == str(FIXTURE))
    ).first()
    if repo is None:
        repo = Repository(name="python-bug-repo", source="local", path_or_url=str(FIXTURE))
        session.add(repo)
        session.flush()
    return repo


def _analysis(session: Session, repo: Repository) -> None:
    analysis = session.scalars(
        select(RepositoryAnalysis).where(RepositoryAnalysis.repository_id == repo.id)
    ).first()
    if analysis is None:
        analysis = RepositoryAnalysis(repository_id=repo.id)
        session.add(analysis)
    analysis.languages = ["python"]
    analysis.package_managers = ["pip"]
    analysis.dependency_files = []
    analysis.test_locations = ["test_app.py"]
    analysis.ci_workflows = []
    analysis.runtime_versions = {"python": "3.12"}
    analysis.supported = True
    analysis.size_bytes = sum(f.stat().st_size for f in FIXTURE.rglob("*") if f.is_file())

    commands = session.scalars(
        select(RepositoryCommand).where(RepositoryCommand.repository_id == repo.id)
    ).first()
    if commands is None:
        commands = RepositoryCommand(repository_id=repo.id)
        session.add(commands)
    commands.install = None  # fixture has no dependencies
    commands.test = "pytest -v"
    commands.test_framework = "pytest"


def _tasks(session: Session, repo: Repository) -> list[BenchmarkTask]:
    tasks = []
    for title, prompt in TASKS:
        task = session.scalars(
            select(BenchmarkTask).where(
                BenchmarkTask.repository_id == repo.id, BenchmarkTask.title == title
            )
        ).first()
        if task is None:
            task = BenchmarkTask(
                repository_id=repo.id, kind="user_defined", title=title, prompt=prompt
            )
            session.add(task)
            session.flush()
        tasks.append(task)
    return tasks


def _experiment(session: Session, repo: Repository, tasks: list[BenchmarkTask]) -> Experiment:
    """A DRAFT experiment — no combinations, no runs, nothing queued.

    Left as a template the user starts explicitly, because starting it spends
    real model quota (see ADR-003: ~50 free requests/day).
    """
    name = "example: 2 harnesses x 3 models"
    exp = session.scalars(
        select(Experiment).where(
            Experiment.repository_id == repo.id, Experiment.name == name
        )
    ).first()
    if exp is None:
        exp = Experiment(repository_id=repo.id, name=name)
        session.add(exp)
    exp.status = "draft"
    exp.repetitions = 1
    exp.config = {
        "fixture_path": str(FIXTURE),
        "commands": {"test": "pytest -v"},
        "test_framework": "pytest",
        "max_model_requests": 8,
        "timeout_seconds": 1800,
        "max_steps": 50,
        "temperature": 0.0,
        "candidate_harnesses": HARNESSES,
        "candidate_models": MODELS,
        "candidate_task_ids": [t.id for t in tasks],
    }
    return exp


def main() -> int:
    if not FIXTURE.is_dir():
        print(f"fixture not found: {FIXTURE}", file=sys.stderr)
        return 1

    ensure_schema()
    with SessionLocal() as session:
        repo = _repository(session)
        _analysis(session, repo)
        tasks = _tasks(session, repo)
        exp = _experiment(session, repo, tasks)
        session.commit()

        print(f"repository   {repo.id}  {repo.name}")
        for task in tasks:
            print(f"task         {task.id}  {task.title}")
        print(f"experiment   {exp.id}  {exp.name} (draft)")
        print()
        print(f"matrix would be {len(HARNESSES)} harnesses x {len(MODELS)} models "
              f"x {len(tasks)} tasks x {exp.repetitions} rep "
              f"= {len(HARNESSES) * len(MODELS) * len(tasks) * exp.repetitions} runs")
        print("nothing queued — starting it spends real model quota (see ADR-003)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

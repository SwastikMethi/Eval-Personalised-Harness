from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import BaselineResult, Repository, RepositoryAnalysis, RepositoryCommand
from app.repositories import baseline, detectors, service

router = APIRouter()


def _repo_or_404(repo_id: str, session: Session) -> Repository:
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    return repo


def _repo_root(repo: Repository) -> Any:
    try:
        if repo.source == "local":
            return service.register_local(repo.path_or_url)
        return service.clone_github(repo.path_or_url, repo.id)
    except service.RepositoryError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/repositories/{repo_id}/analyze")
def analyze(repo_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = _repo_or_404(repo_id, session)
    root = _repo_root(repo)
    branch, commit = service.head_info(root)
    repo.default_branch, repo.current_commit = branch, commit
    result = detectors.analyze_repository(root)
    analysis = RepositoryAnalysis(
        repository_id=repo.id,
        languages=result.languages,
        package_managers=result.package_managers,
        dependency_files=result.dependency_files,
        test_locations=result.test_locations,
        ci_workflows=result.ci_workflows,
        runtime_versions=result.runtime_versions,
        supported=result.supported,
        size_bytes=result.size_bytes,
    )
    session.add(analysis)
    commands = session.scalars(
        select(RepositoryCommand).where(RepositoryCommand.repository_id == repo.id)
    ).first()
    if commands is None:
        c = result.commands
        session.add(
            RepositoryCommand(
                repository_id=repo.id,
                install=c.install,
                build=c.build,
                test=c.test,
                lint=c.lint,
                typecheck=c.typecheck,
                test_framework=c.test_framework,
            )
        )
    session.commit()
    return {"analysis_id": analysis.id, "supported": result.supported}


@router.get("/repositories/{repo_id}/analysis")
def get_analysis(repo_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    _repo_or_404(repo_id, session)
    analysis = session.scalars(
        select(RepositoryAnalysis)
        .where(RepositoryAnalysis.repository_id == repo_id)
        .order_by(RepositoryAnalysis.created_at.desc())
    ).first()
    commands = session.scalars(
        select(RepositoryCommand).where(RepositoryCommand.repository_id == repo_id)
    ).first()
    if analysis is None:
        raise HTTPException(404, "no analysis yet — POST /analyze first")
    return {
        "languages": analysis.languages,
        "package_managers": analysis.package_managers,
        "dependency_files": analysis.dependency_files,
        "test_locations": analysis.test_locations,
        "ci_workflows": analysis.ci_workflows,
        "runtime_versions": analysis.runtime_versions,
        "supported": analysis.supported,
        "size_bytes": analysis.size_bytes,
        "commands": {
            "install": commands.install if commands else None,
            "build": commands.build if commands else None,
            "test": commands.test if commands else None,
            "lint": commands.lint if commands else None,
            "typecheck": commands.typecheck if commands else None,
            "test_framework": commands.test_framework if commands else None,
            "user_edited": commands.user_edited if commands else False,
        },
    }


class CommandsIn(BaseModel):
    install: str | None = None
    build: str | None = None
    test: str | None = None
    lint: str | None = None
    typecheck: str | None = None
    test_framework: str | None = None


@router.put("/repositories/{repo_id}/commands")
def update_commands(
    repo_id: str, body: CommandsIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    _repo_or_404(repo_id, session)
    commands = session.scalars(
        select(RepositoryCommand).where(RepositoryCommand.repository_id == repo_id)
    ).first()
    if commands is None:
        commands = RepositoryCommand(repository_id=repo_id)
        session.add(commands)
    for name in ("install", "build", "test", "lint", "typecheck", "test_framework"):
        setattr(commands, name, getattr(body, name))
    commands.user_edited = True
    session.commit()
    return {"ok": True}


@router.get("/repositories/{repo_id}/commits")
def commits(repo_id: str, session: Session = Depends(get_session)) -> list[dict[str, str]]:
    repo = _repo_or_404(repo_id, session)
    root = _repo_root(repo)
    return service.list_commits(root)


@router.post("/repositories/{repo_id}/baseline")
def run_baseline_endpoint(
    repo_id: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    repo = _repo_or_404(repo_id, session)
    root = _repo_root(repo)
    _, commit = service.head_info(root)
    commands = session.scalars(
        select(RepositoryCommand).where(RepositoryCommand.repository_id == repo_id)
    ).first()
    if commands is None:
        raise HTTPException(409, "analyze the repository first to detect commands")

    import tempfile
    from pathlib import Path

    workdir = Path(tempfile.mkdtemp(prefix="aso-baseline-"))
    snapshot = workdir / "snapshot"
    try:
        service.create_snapshot(root, commit, snapshot)
        outcome = baseline.run_baseline(
            snapshot,
            {
                "install": commands.install,
                "build": commands.build,
                "test": commands.test,
                "lint": commands.lint,
                "typecheck": commands.typecheck,
            },
            commands.test_framework,
        )
    except service.RepositoryError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)

    record = BaselineResult(
        repository_id=repo_id,
        base_commit=commit,
        benchmarkable=outcome.benchmarkable,
        warn=outcome.warn,
        steps=outcome.steps,
        test_cases=[list(c) for c in outcome.test_cases],
    )
    session.add(record)
    session.commit()
    return {
        "baseline_id": record.id,
        "benchmarkable": outcome.benchmarkable,
        "warn": outcome.warn,
        "steps": {k: {"exit_code": v["exit_code"]} for k, v in outcome.steps.items()},
    }

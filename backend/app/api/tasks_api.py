from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import BenchmarkTask, HiddenTestCandidate, Repository
from app.providers.openrouter import ProviderError
from app.repositories import service
from app.repositories.suggest import SuggestionError
from app.tasks import historical

router = APIRouter()


class CommitTaskIn(BaseModel):
    repository_id: str
    sha: str


@router.post("/tasks/from-commit")
def create_task_from_commit(
    body: CommitTaskIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    repo = session.get(Repository, body.repository_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    try:
        root = (
            service.register_local(repo.path_or_url)
            if repo.source == "local"
            else service.clone_github(repo.path_or_url, repo.id)
        )
        commits = {c["sha"]: c for c in service.list_commits(root, limit=200)}
        if body.sha not in commits:
            raise HTTPException(404, "commit not found in recent history")
        base = commits[body.sha]["parent"]
        if not base:
            raise HTTPException(422, "root commit has no parent to use as base state")
        title, prompt = historical.commit_task_description(root, body.sha)
        extractions = historical.extract_hidden_tests(root, base, body.sha)
    except service.RepositoryError as exc:
        raise HTTPException(422, str(exc)) from exc

    task = BenchmarkTask(
        repository_id=repo.id, kind="commit", title=title, prompt=prompt, base_commit=base
    )
    session.add(task)
    session.flush()
    for ext in extractions:
        session.add(
            HiddenTestCandidate(
                task_id=task.id,
                relpath=ext.relpath,
                content=ext.content,
                change_type=ext.change_type,
                confidence=ext.confidence,
                reject_reason=ext.reject_reason,
                # low-confidence candidates start unapproved; user decides
                approved=True if ext.confidence == "high" else None,
            )
        )
    session.commit()
    return {
        "id": task.id,
        "base_commit": base,
        "hidden_test_candidates": len(extractions),
    }


class ProposeIn(BaseModel):
    model_id: str | None = None


@router.post("/repositories/{repository_id}/propose-tasks")
async def propose_tasks_endpoint(
    repository_id: str, body: ProposeIn | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Propose comprehension tasks, each with the rubric that will grade it.

    Creates the tasks immediately so they can be ticked like commits, and
    stores each rubric beside them. The rubric is written by the same call that
    writes the question, against the same digest, so its criteria are concrete
    and BOTH harnesses are later scored against exactly the same list — which
    is what makes the comparison a comparison rather than two opinions.
    """
    from app.core.config import settings as cfg
    from app.repositories import analyzer as analyzer_mod
    from app.repositories import digest as digest_mod
    from app.tasks import propose

    repo = session.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    try:
        root = (
            service.register_local(repo.path_or_url)
            if repo.source == "local"
            else service.clone_github(repo.path_or_url, repo.id)
        )
        commits = service.list_commits(root, limit=digest_mod.MAX_COMMITS)
    except service.RepositoryError as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        analyzer = analyzer_mod.select_analyzer(cfg, body.model_id if body else None)
        model_id = await analyzer_mod.resolve_model(analyzer)
    except analyzer_mod.AnalyzerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc

    digest = digest_mod.build_digest(root, commits)
    try:
        proposed = await propose.propose_tasks(analyzer.provider, model_id, digest)
    except SuggestionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(502, f"[{exc.category}] {exc}") from exc

    created: list[dict[str, Any]] = []
    for item in proposed:
        task = BenchmarkTask(
            repository_id=repo.id,
            kind="theory",
            title=item.title,
            # The answer has to land somewhere uniform across harnesses.
            prompt=item.prompt + propose.ANSWER_INSTRUCTION,
            base_commit=None,
        )
        session.add(task)
        session.flush()
        propose.save_rubric(task.id, item)
        created.append(
            {
                "id": task.id,
                "category": item.category,
                "title": item.title,
                "prompt": task.prompt,
                "rubric": [
                    {"criterion": c.criterion, "evidence": c.evidence, "depth": c.depth}
                    for c in item.rubric
                ],
                # Criteria the proposer invented, shown rather than hidden: a
                # model citing paths that do not exist is worth knowing about.
                "dropped": item.dropped,
            }
        )
    session.commit()
    return {"provenance": analyzer.provenance, "tasks": created}


class PrepareIn(BaseModel):
    # The task stores its BASE commit, not the solution commit, and a base can
    # have more than one child — so the caller names the commit it replayed.
    sha: str


@router.post("/tasks/{task_id}/prepare")
async def prepare_task(
    task_id: str, body: PrepareIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Turn a replayed commit into something that can actually grade an agent.

    Two model-backed steps, kept off `/tasks/from-commit` because that runs on
    every checkbox tick and these take minutes: the prompt is rewritten as a
    present-tense problem statement, and when the commit shipped no tests of its
    own a hidden test is generated and PROVEN to fail before the fix and pass
    after it. Both degrade to the deterministic behaviour rather than failing.
    """
    from app.core.config import settings as cfg
    from app.models import RepositoryCommand
    from app.repositories import analyzer as analyzer_mod
    from app.tasks import generate_tests

    task = session.get(BenchmarkTask, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    repo = session.get(Repository, task.repository_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    if not task.base_commit:
        raise HTTPException(422, "task has no base commit — nothing to replay against")

    try:
        analyzer = analyzer_mod.select_analyzer(cfg)
        model_id = await analyzer_mod.resolve_model(analyzer)
    except analyzer_mod.AnalyzerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc

    try:
        root = (
            service.register_local(repo.path_or_url)
            if repo.source == "local"
            else service.clone_github(repo.path_or_url, repo.id)
        )
    except service.RepositoryError as exc:
        raise HTTPException(422, str(exc)) from exc

    # Keep the real diff for grading. ADR-005 lets a model score the agent's
    # change against it, and this is the one place the solution sha is known —
    # the task row stores only the BASE commit.
    from app.tasks import propose

    try:
        propose.save_task_meta(
            task.id,
            {
                "solution_sha": body.sha,
                "reference_diff": generate_tests.commit_diff(root, task.base_commit, body.sha)[
                    :20000
                ],
            },
        )
    except Exception:  # noqa: BLE001 - grading degrades, task creation must not fail
        pass

    title, prompt = await historical.ai_task_description(
        root, body.sha, analyzer.provider, model_id
    )
    # ai_task_description falls back silently on refusal, provider error or a
    # leaked fix. Two cheap git reads tell the user which one they got, rather
    # than showing "model" over a description the model never wrote.
    prompt_is_ai = prompt != historical.commit_task_description(root, body.sha)[1]
    task.title, task.prompt = title, prompt

    # Only generate when extraction found nothing usable. A test that shipped
    # with the commit is better evidence than one written about it.
    existing = session.scalars(
        select(HiddenTestCandidate).where(HiddenTestCandidate.task_id == task.id)
    ).all()
    generated: dict[str, Any] | None = None
    if not any(c.confidence == "high" for c in existing):
        commands = session.scalars(
            select(RepositoryCommand).where(RepositoryCommand.repository_id == repo.id)
        ).first()
        if commands is None:
            raise HTTPException(409, "analyze the repository first to detect commands")

        result = await generate_tests.generate_verified_test(
            provider=analyzer.provider,
            model_id=model_id,
            root=root,
            parent=task.base_commit,
            target=body.sha,
            subject=title,
            commands={"install": commands.install, "test": commands.test},
            framework=commands.test_framework,
            repo_id=repo.id,
        )
        if result.content:
            session.add(
                HiddenTestCandidate(
                    task_id=task.id,
                    relpath=result.relpath,
                    content=result.content,
                    change_type="generated",
                    # "high" means PROVEN to discriminate, never "the model
                    # sounded sure" — that distinction is the whole feature.
                    confidence="high" if result.verified else "low",
                    reject_reason=result.reject_reason,
                    # Verified or not, a generated test waits for the user.
                    approved=None,
                )
            )
        generated = {
            "relpath": result.relpath,
            "verified": result.verified,
            "reject_reason": result.reject_reason,
            "attempts": result.attempts,
            "evidence": result.evidence,
        }

    session.commit()
    return {
        "task_id": task.id,
        "title": task.title,
        "prompt": task.prompt,
        "prompt_source": "model" if prompt_is_ai else "commit-message",
        "provenance": analyzer.provenance,
        "generated_test": generated,
    }


@router.get("/tasks/{task_id}/hidden-tests")
def list_hidden_tests(
    task_id: str, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    candidates = session.scalars(
        select(HiddenTestCandidate).where(HiddenTestCandidate.task_id == task_id)
    ).all()
    return [
        {
            "id": c.id,
            "relpath": c.relpath,
            "change_type": c.change_type,
            "confidence": c.confidence,
            "reject_reason": c.reject_reason,
            "approved": c.approved,
        }
        for c in candidates
    ]


class ApprovalIn(BaseModel):
    approved: bool


@router.put("/hidden-tests/{candidate_id}")
def set_hidden_test_approval(
    candidate_id: str, body: ApprovalIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    candidate = session.get(HiddenTestCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "candidate not found")
    candidate.approved = body.approved
    session.commit()
    return {"ok": True}

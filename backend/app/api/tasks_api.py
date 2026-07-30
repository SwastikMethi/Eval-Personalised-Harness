from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import BenchmarkTask, HiddenTestCandidate, Repository
from app.repositories import service
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

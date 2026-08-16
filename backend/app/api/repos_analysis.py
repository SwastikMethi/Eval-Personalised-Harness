from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models import BaselineResult, Repository, RepositoryAnalysis, RepositoryCommand
from app.providers.openrouter import ProviderError
from app.repositories import detectors, service
from app.sandboxes.runner import run_baseline_in_sandbox

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


class SuggestIn(BaseModel):
    model_id: str | None = None


@router.post("/repositories/{repo_id}/suggest")
async def suggest_setup_endpoint(
    repo_id: str, body: SuggestIn | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Infer build/test commands and nominate benchmark commits (spec §6).

    Sends a bounded, secret-free digest of the repository to the model provider
    — the only place in this product that transmits repository content
    anywhere. The result is a SUGGESTION: it is returned for the user to edit
    and save, never applied, and the baseline verifies it afterwards.

    Runs server-side rather than through the run-scoped proxy: there is no run
    here, and the API key must not leave the backend either way.

    Uses the SAME analyzer as /evaluation-strategy. This endpoint used to build
    an OpenRouter provider directly and 409 without that key, so two adjacent
    buttons in the wizard silently spent two different vendors' quota and
    ANALYZER_PROVIDER only governed one of them.
    """
    from app.core.config import settings as cfg
    from app.repositories import analyzer as analyzer_mod
    from app.repositories import digest as digest_mod
    from app.repositories import suggest as suggest_mod

    repo = _repo_or_404(repo_id, session)
    root = _repo_root(repo)

    try:
        analyzer = analyzer_mod.select_analyzer(cfg, body.model_id if body else None)
        model_id = await analyzer_mod.resolve_model(analyzer)
    except analyzer_mod.AnalyzerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc

    try:
        commits = service.list_commits(root, limit=digest_mod.MAX_COMMITS)
    except service.RepositoryError:
        commits = []

    bundle = digest_mod.build_digest(root, commits)
    detected = detectors.analyze_repository(root)
    hint = {
        "languages": detected.languages,
        "package_managers": detected.package_managers,
        "commands": {
            f: getattr(detected.commands, f, None)
            for f in ("install", "build", "test", "lint", "typecheck", "test_framework")
        },
    }

    try:
        suggestion = await suggest_mod.suggest_setup(
            analyzer.provider, model_id, bundle, hint
        )
    except suggest_mod.SuggestionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(502, f"[{exc.category}] {exc}") from exc

    by_sha = {c["sha"]: c for c in commits}
    return {
        "model_id": suggestion.model_id,
        # Which vendor actually answered. Without it, "the AI suggested this"
        # is unattributable — and this endpoint answered from a different
        # provider than its neighbour for long enough to matter.
        "provenance": analyzer.provenance,
        "confidence": suggestion.confidence,
        "commands": {**suggestion.commands, "test_framework": suggestion.test_framework},
        "rationale": suggestion.rationale,
        "commits": [
            {
                "sha": c["sha"],
                "why": c["why"],
                "subject": by_sha.get(c["sha"], {}).get("subject", ""),
                "parent": by_sha.get(c["sha"], {}).get("parent", ""),
            }
            for c in suggestion.commits
        ],
        "files_read": sorted(bundle.files),
    }


def _baseline_payload(record: BaselineResult) -> dict[str, Any]:
    return {
        "baseline_id": record.id,
        "base_commit": record.base_commit,
        "benchmarkable": record.benchmarkable,
        "warn": record.warn,
        # Include the tail of failing output. Without it "exit 2" is
        # undiagnosable without opening the database by hand.
        "steps": {
            k: {
                "exit_code": v.get("exit_code"),
                "output": (v.get("stdout") or "")[-4000:] if v.get("exit_code") else "",
            }
            for k, v in (record.steps or {}).items()
        },
        "test_case_count": len(record.test_cases or []),
    }


@router.get("/repositories/{repo_id}/baseline")
def latest_baseline(repo_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Most recent baseline for a repo.

    The wizard kicks a baseline off in the background and reviews it later, so
    it needs to read the outcome without re-running install and the test suite.
    """
    _repo_or_404(repo_id, session)
    record = session.scalars(
        select(BaselineResult)
        .where(BaselineResult.repository_id == repo_id)
        .order_by(BaselineResult.created_at.desc())
    ).first()
    if record is None:
        raise HTTPException(404, "no baseline yet — POST /baseline first")
    return _baseline_payload(record)


class AnalyzeIn(BaseModel):
    model_id: str | None = None


def _signal(benchmarkable: bool, cases: Any) -> tuple[int, int]:
    """(usable, passing) — compared lexicographically, higher is better.

    A suite that does not run at all reports zero failures, which naively looks
    better than one that runs and fails. Ranking usability first stops a repair
    that breaks collection from being recorded as an improvement.
    """
    passed = sum(1 for entry in (cases or []) if tuple(entry)[1] == "passed")
    return (1 if benchmarkable else 0, passed)


@router.post("/repositories/{repo_id}/prepare-tests")
async def prepare_tests_endpoint(
    repo_id: str, body: AnalyzeIn | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Make the repo's own suite runnable — without fixing the bug (spec §7).

    Only test configuration, dependency manifests and test files may change;
    `app/repositories/repair.py` enforces that on the returned diff rather than
    asking for it, because repairing application source would delete the very
    bug an agent is asked to fix and hand every harness full marks.

    The patch is kept only if it measurably improves the baseline, and it is
    then applied to the agent's workspace AND the graded tree alike.
    """
    import tempfile
    from pathlib import Path

    from app.core.config import settings as cfg
    from app.repositories import analyzer as analyzer_mod
    from app.repositories import repair as repair_mod

    repo = _repo_or_404(repo_id, session)
    root = _repo_root(repo)

    before = session.scalars(
        select(BaselineResult)
        .where(BaselineResult.repository_id == repo_id)
        .order_by(BaselineResult.created_at.desc())
    ).first()
    if before is None:
        raise HTTPException(409, "run a baseline first — there is nothing to compare against")

    commands = session.scalars(
        select(RepositoryCommand).where(RepositoryCommand.repository_id == repo_id)
    ).first()
    if commands is None:
        raise HTTPException(409, "analyze the repository first to detect commands")

    try:
        analyzer = analyzer_mod.select_analyzer(cfg, body.model_id if body else None)
        model_id = await analyzer_mod.resolve_model(analyzer)
    except analyzer_mod.AnalyzerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc

    try:
        patch = await repair_mod.propose_repair(
            analyzer.provider, model_id, root, before.steps or {}, []
        )
    except repair_mod.RepairError as exc:
        return {
            "applied": False,
            "reason": str(exc),
            "provenance": analyzer.provenance,
            "changed_paths": [],
        }
    except ProviderError as exc:
        raise HTTPException(502, f"[{exc.category}] {exc}") from exc

    command_map = {
        "install": commands.install,
        "build": commands.build,
        "test": commands.test,
    }
    workdir = Path(tempfile.mkdtemp(prefix="aso-repair-"))
    snapshot = workdir / "snapshot"
    try:
        _, commit = service.head_info(root)
        service.create_snapshot(root, commit, snapshot)
        applied, apply_error = repair_mod.apply_patch(snapshot, patch)
        if not applied:
            return {
                "applied": False,
                "reason": f"patch does not apply cleanly: {apply_error}",
                "provenance": analyzer.provenance,
                "changed_paths": repair_mod.patched_paths(patch),
            }
        after = run_baseline_in_sandbox(
            snapshot, command_map, commands.test_framework, repo_id
        )
    except service.RepositoryError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)

    before_signal = _signal(before.benchmarkable, before.test_cases)
    after_signal = _signal(after.benchmarkable, after.test_cases)
    if after_signal <= before_signal:
        # Kept honest: a patch that did not help is discarded rather than saved
        # on the strength of having applied cleanly.
        return {
            "applied": False,
            "reason": (
                f"patch did not improve the baseline "
                f"(usable/passing {before_signal} → {after_signal})"
            ),
            "provenance": analyzer.provenance,
            "changed_paths": repair_mod.patched_paths(patch),
        }

    repair_mod.save_fixup(repo_id, patch)
    return {
        "applied": True,
        "reason": "",
        "provenance": analyzer.provenance,
        "changed_paths": repair_mod.patched_paths(patch),
        "before": {"benchmarkable": before.benchmarkable, "passing": before_signal[1]},
        "after": {"benchmarkable": after.benchmarkable, "passing": after_signal[1]},
        "patch": patch,
    }


# NOT /analyze — that is already the deterministic detector sweep above, and a
# duplicate path silently resolves to whichever route registered first.
@router.post("/repositories/{repo_id}/evaluation-strategy")
async def decide_evaluation_strategy_endpoint(
    repo_id: str, body: AnalyzeIn | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Decide how this repository can be evaluated — and prove it (spec §11).

    A model proposes commands; the ladder then VERIFIES them by running a
    baseline in a container and walks down until something produces real
    signal. The user is told the answer, including "unbenchmarkable", before
    any credits are spent on a matrix — which is the failure this replaces:
    two real patches on a repo that could never be scored.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from app.core.config import settings as cfg
    from app.repositories import analyzer as analyzer_mod
    from app.repositories import digest as digest_mod
    from app.repositories import strategy as strategy_mod
    from app.repositories import suggest as suggest_mod
    from app.tasks import historical

    repo = _repo_or_404(repo_id, session)
    root = _repo_root(repo)

    try:
        analyzer = analyzer_mod.select_analyzer(cfg, body.model_id if body else None)
        model_id = await analyzer_mod.resolve_model(analyzer)
    except analyzer_mod.AnalyzerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc

    try:
        commits = service.list_commits(root, limit=digest_mod.MAX_COMMITS)
    except service.RepositoryError:
        commits = []

    detected = detectors.analyze_repository(root)
    hint = {
        "languages": detected.languages,
        "package_managers": detected.package_managers,
        "commands": {
            f: getattr(detected.commands, f, None)
            for f in ("install", "build", "test", "lint", "typecheck", "test_framework")
        },
    }
    try:
        suggestion = await suggest_mod.suggest_setup(
            analyzer.provider, model_id, digest_mod.build_digest(root, commits), hint
        )
    except suggest_mod.SuggestionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(502, f"[{exc.category}] {exc}") from exc

    # Rung 1 evidence: do the nominated commits actually carry tests? Counted
    # from the diff, never from the model's opinion of the diff.
    commit_test_count = 0
    nominated = [c.get("sha", "") for c in suggestion.commits][:5]
    by_sha = {c["sha"]: c for c in commits}
    for sha in nominated:
        parent = (by_sha.get(sha) or {}).get("parent")
        if not parent:
            continue
        try:
            found = historical.extract_hidden_tests(root, parent, sha)
        except Exception:  # noqa: BLE001 - a bad commit must not fail the analysis
            continue
        commit_test_count += sum(1 for e in found if e.confidence == "high")

    commands = {k: suggestion.commands.get(k) for k in ("install", "build", "test")}

    def _baseline() -> Any:
        workdir = Path(tempfile.mkdtemp(prefix="aso-analyze-"))
        snapshot = workdir / "snapshot"
        try:
            _, commit = service.head_info(root)
            service.create_snapshot(root, commit, snapshot)
            return run_baseline_in_sandbox(
                snapshot, dict(commands), suggestion.test_framework, repo_id
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    decision = strategy_mod.decide_strategy(
        commands=commands,
        test_framework=suggestion.test_framework,
        commit_test_count=commit_test_count,
        run_baseline=_baseline,
        provenance=analyzer.provenance,
    )

    return {
        "strategy": decision.strategy,
        "scoreable": decision.scoreable,
        "meaning": decision.meaning,
        "warn": decision.warn,
        "commands": {**decision.commands, "test_framework": decision.test_framework},
        "provenance": decision.provenance,
        "rationale": suggestion.rationale,
        "attempts": [
            {
                "rung": a.rung,
                "strategy": a.strategy,
                "ok": a.ok,
                "reason": a.reason,
                "evidence": a.evidence,
            }
            for a in decision.attempts
        ],
        "commits": [
            {**by_sha.get(c.get("sha", ""), {}), "why": c.get("why", "")}
            for c in suggestion.commits
            if c.get("sha") in by_sha
        ],
    }


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
    command_map = {
        "install": commands.install,
        "build": commands.build,
        "test": commands.test,
        "lint": commands.lint,
        "typecheck": commands.typecheck,
    }
    try:
        service.create_snapshot(root, commit, snapshot)
        outcome = run_baseline_in_sandbox(
            snapshot, command_map, commands.test_framework, repo_id
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
    # Same shape as GET so the client has one type for both paths.
    return _baseline_payload(record)

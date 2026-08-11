import subprocess
from pathlib import Path

import pytest

from app.repositories.baseline import run_baseline
from app.repositories.service import (
    RepositoryError,
    create_snapshot,
    head_info,
    list_commits,
    register_local,
)


def make_git_repo(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=root,
        check=True,
    )


def test_register_local_ok(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    make_git_repo(repo, {"a.txt": "hi"})
    assert register_local(str(repo)) == repo.resolve()


def test_register_local_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError, match="traversal"):
        register_local(str(tmp_path / ".." / "x"))


def test_register_local_rejects_non_git(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError, match="not a git repository"):
        register_local(str(tmp_path))


def test_submodule_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    make_git_repo(repo, {".gitmodules": '[submodule "x"]', "a.txt": "hi"})
    with pytest.raises(RepositoryError, match="submodules"):
        register_local(str(repo))


def test_lfs_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    make_git_repo(repo, {".gitattributes": "*.bin filter=lfs", "a.txt": "hi"})
    with pytest.raises(RepositoryError, match="LFS"):
        register_local(str(repo))


def test_snapshot_has_no_history_or_remotes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    make_git_repo(repo, {"a.txt": "v1"})
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/x.git"], cwd=repo, check=True
    )
    (repo / "a.txt").write_text("v2")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "second"],
        cwd=repo,
        check=True,
    )
    _, head = head_info(repo)

    snapshot = tmp_path / "snap"
    create_snapshot(repo, head, snapshot)

    assert (snapshot / "a.txt").read_text() == "v2"
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=snapshot, capture_output=True, text=True
    ).stdout
    assert len(log.strip().splitlines()) == 1  # single synthetic commit only
    remotes = subprocess.run(
        ["git", "remote"], cwd=snapshot, capture_output=True, text=True
    ).stdout
    assert remotes.strip() == ""


def test_snapshot_at_parent_excludes_solution(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    make_git_repo(repo, {"a.txt": "base"})
    (repo / "solution.txt").write_text("the answer")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "solution"],
        cwd=repo,
        check=True,
    )
    commits = list_commits(repo)
    base = commits[0]["parent"]  # parent of the solution commit
    snapshot = tmp_path / "snap"
    create_snapshot(repo, base, snapshot)
    assert not (snapshot / "solution.txt").exists()


GH_URL = "https://github.com/owner/repo"


def _fake_clone(dest: Path, origin: str) -> None:
    """A directory that looks exactly like a finished clone of `origin`."""
    make_git_repo(dest, {"a.txt": "hi"})
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=dest, check=True)


def test_existing_clone_is_reused_not_destroyed(tmp_path: Path, monkeypatch) -> None:
    """Re-cloning on every call let a background baseline delete the tree a
    concurrent `git log` was reading, so GitHub repos looked commit-less."""
    from app.core.config import settings
    from app.repositories import service

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    dest = tmp_path / "repos" / "repo-1"
    dest.parent.mkdir(parents=True)
    _fake_clone(dest, GH_URL)
    (dest / "sentinel.txt").write_text("must survive")

    # No network: a reused clone must never shell out to `git clone`.
    monkeypatch.setattr(
        service, "_do_clone", lambda *a, **k: pytest.fail("re-cloned an existing repo")
    )
    assert service.clone_github(GH_URL, "repo-1") == dest
    assert (dest / "sentinel.txt").read_text() == "must survive"


def test_trailing_slash_still_matches_the_existing_clone(
    tmp_path: Path, monkeypatch
) -> None:
    from app.core.config import settings
    from app.repositories import service

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    dest = tmp_path / "repos" / "repo-2"
    dest.parent.mkdir(parents=True)
    _fake_clone(dest, GH_URL)
    monkeypatch.setattr(
        service, "_do_clone", lambda *a, **k: pytest.fail("re-cloned on a trailing slash")
    )
    assert service.clone_github(f"{GH_URL}/", "repo-2") == dest


def test_directory_for_a_different_remote_is_replaced(tmp_path: Path, monkeypatch) -> None:
    from app.core.config import settings
    from app.repositories import service

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    dest = tmp_path / "repos" / "repo-3"
    dest.parent.mkdir(parents=True)
    _fake_clone(dest, "https://github.com/someone/else")

    called: list[str] = []

    def _fresh(url: str, target: Path) -> Path:
        called.append(url)
        target.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(service, "_do_clone", _fresh)
    service.clone_github(GH_URL, "repo-3")
    assert called == [GH_URL], "a clone of the wrong remote must not be reused"


def test_concurrent_calls_do_not_race(tmp_path: Path, monkeypatch) -> None:
    """Two threads asking for the same repo must serialize, not interleave."""
    import threading as _threading

    from app.core.config import settings
    from app.repositories import service

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "repos").mkdir(parents=True)
    overlaps: list[int] = []
    inside = 0

    def _slow(url: str, target: Path) -> Path:
        nonlocal inside
        inside += 1
        overlaps.append(inside)
        import time

        time.sleep(0.05)
        inside -= 1
        target.mkdir(parents=True, exist_ok=True)
        _fake_clone(target, url) if not (target / ".git").exists() else None
        return target

    monkeypatch.setattr(service, "_do_clone", _slow)
    threads = [
        _threading.Thread(target=service.clone_github, args=(GH_URL, "repo-4")) for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max(overlaps) == 1, "clones of the same repo overlapped"


def test_list_commits_includes_parent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    make_git_repo(repo, {"a.txt": "1"})
    commits = list_commits(repo)
    assert len(commits) == 1
    assert commits[0]["parent"] == ""  # root commit has no parent


def test_baseline_warn_and_proceed(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outcome = run_baseline(
        ws,
        {"install": None, "build": None, "test": "echo 'x.py::test_a PASSED'; exit 0"},
        "pytest",
    )
    assert outcome.benchmarkable
    assert not outcome.warn

    failing = run_baseline(
        ws,
        {"test": "printf 'x.py::t1 PASSED\\nx.py::t2 FAILED\\n'; exit 1"},
        "pytest",
    )
    assert failing.benchmarkable
    assert failing.warn  # partial failure: proceed with warning
    assert ("x.py::t2", "failed") in failing.test_cases


def test_baseline_install_failure_not_benchmarkable(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outcome = run_baseline(ws, {"install": "exit 1"}, None)
    assert not outcome.benchmarkable

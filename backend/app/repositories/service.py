"""Repository registration, cloning, snapshotting (spec §6, §9).

Snapshot = `git archive` at base commit → fresh dir → new git init + one
synthetic commit. No original history, no remotes, no hooks: the leakage
boundary starts here.
"""

import shutil
import subprocess
from pathlib import Path

from app.core.config import settings

MAX_REPO_BYTES = 500 * 1024 * 1024


class RepositoryError(Exception):
    pass


def _git(args: list[str], cwd: Path, timeout: int = 300) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RepositoryError(f"git {args[0]} failed: {proc.stderr.strip()[:500]}")
    return proc.stdout


def _tree_size(root: Path) -> int:
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def _validate_repo_dir(root: Path) -> None:
    if (root / ".gitmodules").exists():
        raise RepositoryError(
            "repository uses git submodules — not supported yet; vendor them or pick another repo"
        )
    attrs = root / ".gitattributes"
    if attrs.exists() and "filter=lfs" in attrs.read_text(errors="replace"):
        raise RepositoryError("repository uses Git LFS — not supported yet")
    if _tree_size(root) > MAX_REPO_BYTES:
        raise RepositoryError(f"repository exceeds size limit ({MAX_REPO_BYTES} bytes)")


def register_local(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if ".." in Path(path_str).parts:
        raise RepositoryError("path traversal not allowed")
    path = path.resolve()
    if not path.is_dir() or not (path / ".git").exists():
        raise RepositoryError(f"not a git repository: {path}")
    _validate_repo_dir(path)
    return path


def clone_github(url: str, repo_id: str) -> Path:
    if not url.startswith("https://github.com/"):
        raise RepositoryError("only public https://github.com URLs are supported")
    dest = settings.data_dir.resolve() / "repos" / repo_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    proc = subprocess.run(
        ["git", "clone", "--no-recurse-submodules", url, str(dest)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RepositoryError(f"clone failed: {proc.stderr.strip()[:500]}")
    hooks = dest / ".git" / "hooks"
    if hooks.is_dir():
        shutil.rmtree(hooks)  # clone hardening: no repo-supplied hooks execute
    try:
        _validate_repo_dir(dest)
    except RepositoryError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def head_info(repo: Path) -> tuple[str, str]:
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    commit = _git(["rev-parse", "HEAD"], repo).strip()
    return branch, commit


def list_commits(repo: Path, limit: int = 50) -> list[dict[str, str]]:
    out = _git(["log", f"-{limit}", "--pretty=format:%H%x1f%s%x1f%an%x1f%aI"], repo)
    commits = []
    for line in out.splitlines():
        sha, subject, author, date = line.split("\x1f")
        parent = _git(["rev-list", "--parents", "-1", sha], repo).split()
        commits.append(
            {
                "sha": sha,
                "subject": subject,
                "author": author,
                "date": date,
                "parent": parent[1] if len(parent) > 1 else "",
            }
        )
    return commits


def create_snapshot(repo: Path, base_commit: str, dest: Path) -> None:
    """Leakage-proof workspace: archive at base commit, fresh git history."""
    dest.mkdir(parents=True, exist_ok=False)
    archive = dest.parent / f"{dest.name}.tar"
    _git(["archive", "--format=tar", "-o", str(archive), base_commit], repo)
    subprocess.run(["tar", "-xf", str(archive), "-C", str(dest)], check=True, timeout=300)
    archive.unlink()
    _git(["init", "-q", "-b", "main"], dest)
    _git(["add", "-A"], dest)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=sandbox@aso.local",
            "-c",
            "user.name=aso-baseline",
            "commit",
            "-q",
            "-m",
            "baseline snapshot",
        ],
        cwd=dest,
        check=True,
        capture_output=True,
        timeout=60,
    )

"""Historical commit replay (spec §8.2) + conservative hidden-test extraction
(spec §10): diff test files between base and target; candidates that import
implementation existing only in the target are rejected; provenance and
confidence recorded, user approves/rejects before an experiment runs.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TEST_FILE_PATTERNS = (
    r"(^|/)tests?/.*\.py$",
    r"(^|/)test_[^/]+\.py$",
    r"(^|/)[^/]+_test\.py$",
    r".*\.test\.[jt]sx?$",
    r".*\.spec\.[jt]sx?$",
    r"(^|/)__tests__/",
)


def is_test_file(path: str) -> bool:
    return any(re.search(p, path) for p in _TEST_FILE_PATTERNS)


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {proc.stderr[:300]}")
    return proc.stdout


def commit_task_description(repo: Path, sha: str) -> tuple[str, str]:
    """Title + prompt drawn from the commit message (spec §8.2, user-editable).

    The commit text must be FRAMED, not handed over raw. Commit messages are
    written in the past tense about finished work, so an unframed one reads as
    a status report: given "added tool to get pokemon data", an agent replied
    "Acknowledged: ... have been added. Please provide a specific task" and
    stopped without editing a file. Every commit-replay run behaved that way.

    Changed file PATHS are included as orientation. The diff itself never is —
    that would hand over the answer and reduce the benchmark to transcription.
    """
    subject = _git(["log", "-1", "--pretty=%s", sha], repo).strip()
    body = _git(["log", "-1", "--pretty=%b", sha], repo).strip()

    changed: list[str] = []
    try:
        names = _git(["show", "--name-only", "--pretty=format:", sha], repo)
        changed = [line.strip() for line in names.splitlines() if line.strip()]
    except RuntimeError:
        pass  # orientation is a nicety; never fail task creation over it

    described = f"{subject}\n\n{body}".strip()
    parts = [
        "Implement the following change in this repository.",
        "",
        "The change is described below as it was originally written up, in the",
        "past tense. It has NOT been applied here: the repository is at the state",
        "immediately before it. Your job is to make it happen by editing files.",
        "",
        "--- change to implement ---",
        described,
        "--- end ---",
    ]
    if changed:
        listed = "\n".join(f"  {p}" for p in changed[:20])
        parts += [
            "",
            "The original change touched these files. Treat this as orientation,",
            "not instruction — solve the problem properly rather than matching it:",
            listed,
        ]
    parts += [
        "",
        "Finish by leaving your work saved in the working tree.",
    ]
    return subject, "\n".join(parts)


@dataclass
class HiddenTestExtraction:
    relpath: str
    content: str
    change_type: str  # added | modified
    confidence: str  # high | low
    reject_reason: str | None = None


def _imports_of(content: str) -> set[str]:
    modules: set[str] = set()
    for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", content, re.M):
        modules.add(m.group(1).split(".")[0])
    return modules


def extract_hidden_tests(repo: Path, base: str, target: str) -> list[HiddenTestExtraction]:
    diff = _git(["diff", "--name-status", base, target], repo)
    base_files = set(_git(["ls-tree", "-r", "--name-only", base], repo).splitlines())
    base_modules = {Path(f).stem for f in base_files if f.endswith(".py")}
    target_files = set(_git(["ls-tree", "-r", "--name-only", target], repo).splitlines())
    target_only_modules = {
        Path(f).stem for f in (target_files - base_files) if f.endswith(".py")
    }

    extractions: list[HiddenTestExtraction] = []
    for line in diff.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if not is_test_file(path) or status.startswith("D"):
            continue
        content = _git(["show", f"{target}:{path}"], repo)
        change_type = "added" if status.startswith("A") else "modified"
        # Reject tests importing implementation that exists ONLY at target:
        # they cannot pass against any agent result missing that new module.
        suspicious = _imports_of(content) & (target_only_modules - base_modules)
        suspicious -= {Path(path).stem}
        if suspicious:
            extractions.append(
                HiddenTestExtraction(
                    relpath=path,
                    content=content,
                    change_type=change_type,
                    confidence="low",
                    reject_reason=f"imports target-only modules: {sorted(suspicious)}",
                )
            )
        else:
            extractions.append(
                HiddenTestExtraction(
                    relpath=path,
                    content=content,
                    change_type=change_type,
                    confidence="high" if change_type == "added" else "low",
                )
            )
    return extractions

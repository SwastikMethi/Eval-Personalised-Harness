import subprocess
from pathlib import Path

from app.tasks.historical import commit_task_description, extract_hidden_tests, is_test_file
from tests.test_repo_service import make_git_repo


def commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()


def test_is_test_file() -> None:
    assert is_test_file("tests/test_x.py")
    assert is_test_file("src/foo.test.ts")
    assert is_test_file("src/__tests__/foo.ts")
    assert not is_test_file("src/app.py")


def test_task_description_from_commit(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    make_git_repo(repo, {"a.py": "x = 1\n"})
    sha = commit(repo, "fix: handle empty input\n\nDetails here.", {"a.py": "x = 2\n"})
    title, prompt = commit_task_description(repo, sha)
    assert title == "fix: handle empty input"
    assert "Details here." in prompt


def test_hidden_test_extraction_and_rejection(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    make_git_repo(repo, {"app.py": "def f(): return 1\n"})
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    target = commit(
        repo,
        "add feature + tests",
        {
            "app.py": "def f(): return 2\n",
            "newmod.py": "def g(): return 3\n",
            "tests/test_ok.py": "from app import f\n\ndef test_f(): assert f() == 2\n",
            "tests/test_needs_newmod.py": "from newmod import g\n\ndef test_g(): assert g()\n",
        },
    )
    extractions = extract_hidden_tests(repo, base, target)
    by_path = {e.relpath: e for e in extractions}
    assert by_path["tests/test_ok.py"].confidence == "high"
    assert by_path["tests/test_ok.py"].reject_reason is None
    needs = by_path["tests/test_needs_newmod.py"]
    assert needs.confidence == "low"
    assert needs.reject_reason is not None and "newmod" in needs.reject_reason

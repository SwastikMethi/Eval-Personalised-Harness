"""Pluggable language detectors (spec §6). Python + JS/TS strong; others
reported as detected-but-unsupported.
"""

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DetectedCommands:
    install: str | None = None
    build: str | None = None
    test: str | None = None
    lint: str | None = None
    typecheck: str | None = None
    test_framework: str | None = None  # parser key: pytest | vitest | generic


@dataclass
class AnalysisResult:
    languages: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    dependency_files: list[str] = field(default_factory=list)
    test_locations: list[str] = field(default_factory=list)
    ci_workflows: list[str] = field(default_factory=list)
    runtime_versions: dict[str, str] = field(default_factory=dict)
    commands: DetectedCommands = field(default_factory=DetectedCommands)
    supported: bool = False
    size_bytes: int = 0


def _detect_python(root: Path, result: AnalysisResult) -> None:
    pyproject = root / "pyproject.toml"
    has_py = any(root.rglob("*.py"))
    if not (has_py or pyproject.exists() or (root / "requirements.txt").exists()):
        return
    result.languages.append("python")
    result.supported = True
    cmds = result.commands
    if (root / "uv.lock").exists():
        result.package_managers.append("uv")
        cmds.install = "uv sync"
        prefix = "uv run "
    elif (root / "poetry.lock").exists():
        result.package_managers.append("poetry")
        cmds.install = "poetry install"
        prefix = "poetry run "
    elif (root / "requirements.txt").exists():
        result.package_managers.append("pip")
        result.dependency_files.append("requirements.txt")
        # `python -m pip` rather than `pip`: a bare `pip` resolves independently
        # of `python`, so on a machine with more than one interpreter it can
        # install into an environment the tests never see — reporting success
        # while the tests then fail on the dependency it "installed".
        cmds.install = "python -m pip install -r requirements.txt"
        prefix = ""
    else:
        result.package_managers.append("pip")
        cmds.install = "python -m pip install -e ." if pyproject.exists() else None
        prefix = ""
    if pyproject.exists():
        result.dependency_files.append("pyproject.toml")
        text = pyproject.read_text(errors="replace")
        if m := re.search(r'requires-python\s*=\s*"([^"]+)"', text):
            result.runtime_versions["python"] = m.group(1)
        if "ruff" in text:
            cmds.lint = f"{prefix}ruff check ."
        if "mypy" in text:
            cmds.typecheck = f"{prefix}mypy ."
    markers = ["pytest.ini", "tox.ini", "setup.cfg", "conftest.py"]
    has_pytest = (
        any((root / m).exists() for m in markers)
        or any(root.rglob("test_*.py"))
        or any(root.rglob("*_test.py"))
        or (pyproject.exists() and "pytest" in pyproject.read_text(errors="replace"))
    )
    if has_pytest:
        # `python -m pytest` rather than `pytest`: the module form puts the
        # CURRENT directory on sys.path, whereas bare pytest puts the first
        # parent without __init__.py there — usually `tests/`. A src-layout
        # repo with no pytest config then cannot import its own package.
        cmds.test = f"{prefix}python -m pytest -v"
        cmds.test_framework = "pytest"
    for loc in ("tests", "test"):
        if (root / loc).is_dir():
            result.test_locations.append(loc)


def _detect_node(root: Path, result: AnalysisResult) -> None:
    pkg_file = root / "package.json"
    if not pkg_file.exists():
        return
    result.languages.append(
        "typescript" if (root / "tsconfig.json").exists() else "javascript"
    )
    result.supported = True
    result.dependency_files.append("package.json")
    cmds = result.commands
    if (root / "pnpm-lock.yaml").exists():
        result.package_managers.append("pnpm")
        runner = "pnpm"
    elif (root / "yarn.lock").exists():
        result.package_managers.append("yarn")
        runner = "yarn"
    else:
        result.package_managers.append("npm")
        runner = "npm"
    cmds.install = cmds.install or f"{runner} install"
    try:
        pkg = json.loads(pkg_file.read_text(errors="replace"))
    except json.JSONDecodeError:
        pkg = {}
    scripts = pkg.get("scripts", {})
    if "build" in scripts:
        cmds.build = cmds.build or f"{runner} run build"
    if "test" in scripts:
        cmds.test = cmds.test or f"{runner} test"
        test_script = scripts["test"]
        cmds.test_framework = cmds.test_framework or (
            "vitest" if ("vitest" in test_script or "jest" in test_script) else "generic"
        )
    if "lint" in scripts:
        cmds.lint = cmds.lint or f"{runner} run lint"
    if (root / "tsconfig.json").exists():
        cmds.typecheck = cmds.typecheck or "npx tsc --noEmit"
    if engines := pkg.get("engines", {}).get("node"):
        result.runtime_versions["node"] = engines
    for loc in ("tests", "test", "spec", "__tests__"):
        if (root / loc).is_dir():
            result.test_locations.append(loc)


_OTHER_MARKERS = {"go": "go.mod", "rust": "Cargo.toml", "java": "pom.xml", "ruby": "Gemfile"}


def analyze_repository(root: Path) -> AnalysisResult:
    result = AnalysisResult()
    _detect_python(root, result)
    _detect_node(root, result)
    for lang, marker in _OTHER_MARKERS.items():
        if (root / marker).exists():
            result.languages.append(f"{lang} (unsupported)")
    ci_dir = root / ".github" / "workflows"
    if ci_dir.is_dir():
        result.ci_workflows = sorted(
            str(p.relative_to(root)) for p in ci_dir.glob("*.y*ml")
        )
    result.size_bytes = sum(
        f.stat().st_size for f in root.rglob("*") if f.is_file() and ".git" not in f.parts
    )
    return result


def _is_vacuous(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A body of only `pass`, a docstring, or `...` — nothing that can fail."""
    for statement in node.body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue  # docstring or a bare `...`
        return False
    return True


def vacuous_test_names(root: Path) -> set[str]:
    """Test functions that succeed no matter what the code does.

    Three of these in a five-test suite is what let an agent score 0.6 for
    editing a README: the two real tests were already failing and so excluded
    as pre-existing, leaving nothing behind the correctness number but
    statements that cannot fail.

    They are named rather than counted because the caller drops them from the
    score's denominator, and a count cannot say which cases to drop. Best
    effort by design — a file that will not parse is not a scoring question.
    """
    names: set[str] = set()
    for path in root.rglob("*.py"):
        if ".git" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name.startswith("test")
                and _is_vacuous(node)
            ):
                names.add(node.name)
    return names

"""Pluggable language detectors (spec §6). Python + JS/TS strong; others
reported as detected-but-unsupported.
"""

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
        cmds.install = "pip install -r requirements.txt"
        prefix = ""
    else:
        result.package_managers.append("pip")
        cmds.install = "pip install -e ." if pyproject.exists() else None
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
        cmds.test = f"{prefix}pytest -v"
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

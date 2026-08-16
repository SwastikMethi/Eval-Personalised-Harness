"""What a repo needs installed before its own install command can run.

`prepared.py` builds one image per repo and runs the repo's install command in
it. That only works if two things are true: the tool the command invokes exists,
and the files the command reads are present. Neither was.

The image is `python:3.12-slim` plus git/node, so `make setup` died with exit
127. And manifests were collected root-only and copied flattened to their
basename, so a repo keeping `backend/pyproject.toml` and `frontend/package.json`
contributed *nothing* to the build context — the Dockerfile was the entire
context, and `cd backend && uv sync` could never have worked even had `make`
been present.

Resolution is deterministic first and costs no model quota. A repo Dockerfile,
when present, is READ for its `apt-get install` lines as evidence — it is never
built, because the harnesses live inside our image and a repo's own `FROM`
would discard them.

Packages come from a fixed allowlist. That is not defensive boilerplate: the
system packages decide what the benchmark can compile and therefore what it
measures, so the set has to be auditable and identical between two runs of the
same repo. The same reasoning is spelled out in `repositories/repair.py`.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Debian packages we are willing to install. Anything outside this set is
# reported rather than installed, so an unbuildable repo is a visible fact
# instead of a silently different environment.
ALLOWED_PACKAGES = frozenset(
    {
        "make",
        "build-essential",
        "gcc",
        "g++",
        "pkg-config",
        "cmake",
        "libpq-dev",
        "libssl-dev",
        "libffi-dev",
        "libxml2-dev",
        "libxslt1-dev",
        "zlib1g-dev",
        "libjpeg-dev",
        "libsqlite3-dev",
        "unzip",
        "rsync",
    }
)

# Files that decide what gets installed. A change to any of them means a
# different environment, so a different image.
DEPENDENCY_MANIFESTS = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements_dev.txt",
    "dev-requirements.txt",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "Pipfile.lock",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "Gemfile",
    "Gemfile.lock",
)

# Not a dependency manifest, but the install command frequently *is* `make x`,
# and a Makefile that is not in the build context makes that command
# unrunnable. Same for the CMake and Taskfile equivalents.
BUILD_FILES = ("Makefile", "makefile", "GNUmakefile", "CMakeLists.txt", "Taskfile.yml")

# Python distributions that build native code on install. Seeing one in a
# manifest means a compiler is needed, which `python:3.12-slim` lacks.
_NEEDS_COMPILER = re.compile(
    r"\b(lxml|psycopg2(?!-binary)|mysqlclient|pyodbc|uwsgi|gevent|cffi|"
    r"cryptography|numpy|scipy|pandas|pillow|matplotlib)\b",
    re.IGNORECASE,
)

_APT_LINE = re.compile(r"apt-get\s+(?:-\w+\s+)*install\s+(.+)", re.IGNORECASE)

# Directories that never contain a manifest we want and cost real time to walk.
_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox", "data"}
)

MAX_CONTEXT_FILES = 60


@dataclass
class EnvironmentSpec:
    """How to build this repo's image."""

    #: Debian packages to apt-install, already intersected with the allowlist.
    system_packages: list[str] = field(default_factory=list)
    #: Repo-relative paths to copy into the build context, structure preserved.
    copy_paths: list[Path] = field(default_factory=list)
    #: "detected" or "model" — shown to the user so the choice is attributable.
    source: str = "detected"
    #: Packages a model or Dockerfile asked for that the allowlist refused.
    rejected: list[str] = field(default_factory=list)

    def identity(self) -> str:
        """Everything that changes the resulting image, as a stable string."""
        packages = ",".join(sorted(self.system_packages))
        paths = ",".join(sorted(str(p) for p in self.copy_paths))
        return f"{packages}|{paths}"


def _candidate_dirs(root: Path) -> list[Path]:
    """The repo root plus its immediate subdirectories.

    One level deep, deliberately. It covers the backend/frontend split that
    defeated the root-only lookup, without turning image resolution into a
    full-tree walk of a repo that may contain a vendored node_modules.
    """
    dirs = [root]
    try:
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name not in _SKIP_DIRS and not child.name.startswith("."):
                dirs.append(child)
    except OSError:
        pass
    return dirs


def discover_files(root: Path) -> list[Path]:
    """Manifests and build files, repo-relative, in a stable order.

    Deduplicated case-insensitively per directory: macOS matches both
    `Makefile` and `makefile` against one file, which would otherwise copy it
    twice and make the image hash differ from Linux for identical content.
    """
    found: list[Path] = []
    for directory in _candidate_dirs(root):
        seen: set[str] = set()
        for name in (*DEPENDENCY_MANIFESTS, *BUILD_FILES):
            path = directory / name
            if not path.is_file():
                continue
            # resolve() gives the on-disk spelling, so two lookups that hit the
            # same inode collapse to one entry.
            key = path.resolve().name.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(path.resolve().relative_to(root.resolve()))
    return found[:MAX_CONTEXT_FILES]


def _packages_from_dockerfile(root: Path) -> tuple[list[str], list[str]]:
    """Packages a repo's own Dockerfile installs — as evidence, not instruction.

    We never build their Dockerfile: our harnesses live in our image and their
    `FROM` would discard them. But if they apt-install libpq-dev to make their
    own code work, that is a strong signal we need it too.
    """
    wanted: list[str] = []
    for directory in _candidate_dirs(root):
        dockerfile = directory / "Dockerfile"
        if not dockerfile.is_file():
            continue
        try:
            text = dockerfile.read_text(errors="replace")
        except OSError:
            continue
        for match in _APT_LINE.finditer(text):
            for token in match.group(1).split():
                # Drop flags, line continuations and shell chaining.
                if token.startswith("-") or token in {"\\", "&&", "|", ";"}:
                    continue
                if token in {"apt-get", "clean", "update", "rm", "-rf"}:
                    break
                wanted.append(token)
    return _split_allowed(wanted)


def _split_allowed(names: list[str]) -> tuple[list[str], list[str]]:
    allowed: list[str] = []
    rejected: list[str] = []
    for name in names:
        clean = name.strip().strip('"\'')
        if not clean:
            continue
        (allowed if clean in ALLOWED_PACKAGES else rejected).append(clean)
    return sorted(set(allowed)), sorted(set(rejected))


def _uses_uv(root: Path, files: list[Path]) -> bool:
    if any(p.name == "uv.lock" for p in files):
        return True
    for rel in (p for p in files if p.name == "pyproject.toml"):
        try:
            data = tomllib.loads((root / rel).read_text(errors="replace"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if "uv" in data.get("tool", {}):
            return True
    return False


def _needs_compiler(root: Path, files: list[Path]) -> bool:
    if any(p.name in {"Cargo.toml", "Cargo.lock"} for p in files):
        return True
    for rel in files:
        if rel.name not in {"requirements.txt", "pyproject.toml", "setup.py", "Pipfile"}:
            continue
        try:
            if _NEEDS_COMPILER.search((root / rel).read_text(errors="replace")):
                return True
        except OSError:
            continue
    return any(root.glob("**/*.pyx"))


def resolve_environment(root: Path, install_cmd: str | None = None) -> EnvironmentSpec:
    """What this repo needs, worked out from its files alone.

    `install_cmd` is consulted only to catch a command whose tool is not implied
    by any file — `make` invoked in a repo that has no Makefile at a depth we
    scan, for instance.
    """
    files = discover_files(root)
    packages: list[str] = []

    if any(p.name in BUILD_FILES for p in files) or (install_cmd or "").strip().startswith("make"):
        packages.append("make")
    if _needs_compiler(root, files):
        packages.append("build-essential")

    hinted, rejected = _packages_from_dockerfile(root)
    packages.extend(hinted)

    allowed, extra_rejected = _split_allowed(packages)
    return EnvironmentSpec(
        system_packages=allowed,
        copy_paths=files,
        source="detected",
        rejected=sorted(set(rejected + extra_rejected)),
    )


def needs_uv(root: Path) -> bool:
    """Whether the repo installs through uv — used by the image build."""
    return _uses_uv(root, discover_files(root))


# Installers that write their output INSIDE the project directory rather than
# into a system location.
_WORKSPACE_LOCAL = re.compile(
    r"\b(uv\s+sync|uv\s+venv|npm\s+(install|ci)|yarn(\s|$)|pnpm\s+install|"
    r"poetry\s+install|bundle\s+install|go\s+mod\s+download|cargo\s+(build|fetch)|make)\b"
)


def installs_into_workspace(install_cmd: str | None) -> bool:
    """Whether baking this install into an image would be wasted work.

    Every container bind-mounts the host workspace over `/workspace`, so
    anything the image wrote *there* is hidden the moment the container starts.
    `pip install` is fine — it populates site-packages, outside the mount, which
    is the case the prepared-image cache was designed around. `uv sync` and
    `npm install` are not: they produce `.venv` and `node_modules` inside the
    project, and the mount discards both.

    Building such an image is not merely useless, it is expensive — `make setup`
    on a monorepo is minutes of uv and npm work thrown away on every cache miss.
    So we skip the image and let the install run as an ordinary step inside the
    container, where it writes into the mounted workspace and the test step that
    follows can actually see it.

    `make` is treated as workspace-local because its target can be anything, and
    guessing wrong costs a long build for nothing.
    """
    if not install_cmd:
        return False
    return bool(_WORKSPACE_LOCAL.search(install_cmd))


__all__ = [
    "ALLOWED_PACKAGES",
    "BUILD_FILES",
    "DEPENDENCY_MANIFESTS",
    "EnvironmentSpec",
    "discover_files",
    "needs_uv",
    "resolve_environment",
]

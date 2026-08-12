"""Per-repo image with dependencies already installed.

Dependencies are unavoidable — correctness comes from running the repo's tests
— but installing them per run is ruinous. A repo pulling streamlit, langchain,
selenium, playwright and faiss-cpu takes minutes, and a 36-run matrix pays that
for every evaluation AND every agent run (the sandbox's PREP phase installs
too). That is hours of pure installation.

So install once at image build time, keyed by a hash of the dependency
manifests, and let every consumer start from that image.

The install command still runs inside the container afterwards. Normally it is
a fast "Requirement already satisfied" no-op; if an agent's patch ADDS a
dependency it installs just that one. That is what makes caching safe rather
than a source of stale-environment bugs.
"""

import hashlib
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.core.config import settings
from app.sandboxes.exec import MAX_OUTPUT_BYTES, CommandResult

log = logging.getLogger(__name__)

# Files whose contents decide what gets installed. A change here means a
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

BUILD_TIMEOUT_S = 1800

_build_locks: dict[str, threading.Lock] = {}
_build_locks_guard = threading.Lock()


def _lock_for(tag: str) -> threading.Lock:
    with _build_locks_guard:
        return _build_locks.setdefault(tag, threading.Lock())


def manifest_files(root: Path) -> list[Path]:
    """Manifests present at the repo root, in a stable order."""
    return [root / name for name in DEPENDENCY_MANIFESTS if (root / name).is_file()]


def manifest_hash(root: Path, install_cmd: str) -> str:
    """Identity of the environment: the manifests plus the command that reads them."""
    digest = hashlib.sha256()
    digest.update(install_cmd.encode())
    for path in manifest_files(root):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def image_tag(repo_id: str, root: Path, install_cmd: str) -> str:
    return f"aso-prepared:{repo_id[:12]}-{manifest_hash(root, install_cmd)}"


def _image_exists(tag: str) -> bool:
    proc = subprocess.run(
        ["docker", "image", "inspect", tag], capture_output=True, timeout=60
    )
    return proc.returncode == 0


def ensure_prepared_image(
    root: Path, install_cmd: str | None, repo_id: str, base_image: str | None = None
) -> tuple[str, CommandResult | None]:
    """Return (image tag, build result).

    The build result is None when nothing had to be built — either the image
    was already cached or there is no install command. When a build FAILS the
    base image is returned along with the failing result, so the caller can
    report it as the install step rather than surfacing an opaque build error.
    """
    base = base_image or settings.eval_image
    if not install_cmd or not install_cmd.strip():
        return base, None

    tag = image_tag(repo_id, root, install_cmd)
    with _lock_for(tag):
        if _image_exists(tag):
            return tag, None

        start = time.monotonic()
        context = Path(tempfile.mkdtemp(prefix="aso-prep-"))
        try:
            for path in manifest_files(root):
                shutil.copy2(path, context / path.name)
            (context / "Dockerfile").write_text(
                f"FROM {base}\n"
                "USER root\n"
                "WORKDIR /workspace\n"
                "COPY . /workspace/\n"
                # Failing here is the repo's install failing; the caller
                # reports it as such rather than as a build error.
                f"RUN {install_cmd}\n"
                "USER 1000\n"
            )
            proc = subprocess.run(
                ["docker", "build", "-t", tag, str(context)],
                capture_output=True,
                timeout=BUILD_TIMEOUT_S,
            )
            output = (proc.stdout or b"") + (proc.stderr or b"")
            result = CommandResult(
                command=install_cmd,
                exit_code=proc.returncode,
                stdout=output[:MAX_OUTPUT_BYTES].decode(errors="replace"),
                stderr="",
                duration_s=time.monotonic() - start,
                truncated=len(output) > MAX_OUTPUT_BYTES,
            )
            if proc.returncode != 0:
                log.warning("prepared image build failed", extra={"tag": tag})
                return base, result
            log.info(
                "prepared image built",
                extra={"tag": tag, "duration": result.duration_s},
            )
            return tag, result
        except subprocess.TimeoutExpired:
            return base, CommandResult(
                command=install_cmd,
                exit_code=-1,
                stdout=f"dependency install exceeded {BUILD_TIMEOUT_S}s",
                stderr="",
                duration_s=time.monotonic() - start,
                timed_out=True,
            )
        finally:
            shutil.rmtree(context, ignore_errors=True)

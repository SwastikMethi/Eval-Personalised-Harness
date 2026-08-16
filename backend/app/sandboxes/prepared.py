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

The saving only exists for installers that write OUTSIDE the project directory.
Every container bind-mounts the host workspace over /workspace, so an image
that populated `.venv` or `node_modules` in there has its work hidden the
instant the container starts. `pip install` lands in site-packages and
survives; `uv sync` and `npm install` do not. For those the build is skipped
entirely — see `environment.installs_into_workspace` — because spending minutes
producing a layer the mount discards is worse than not caching at all.
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
from app.sandboxes.environment import (
    DEPENDENCY_MANIFESTS,
    EnvironmentSpec,
    discover_files,
    installs_into_workspace,
    resolve_environment,
)
from app.sandboxes.exec import MAX_OUTPUT_BYTES, CommandResult

log = logging.getLogger(__name__)

# Re-exported: the canonical list now lives in environment.py alongside the
# build files and the package allowlist that are resolved from it.
__all__ = [
    "DEPENDENCY_MANIFESTS",
    "ensure_prepared_image",
    "image_tag",
    "manifest_files",
    "manifest_hash",
]

BUILD_TIMEOUT_S = 1800

_build_locks: dict[str, threading.Lock] = {}
_build_locks_guard = threading.Lock()


def _lock_for(tag: str) -> threading.Lock:
    with _build_locks_guard:
        return _build_locks.setdefault(tag, threading.Lock())


def manifest_files(root: Path) -> list[Path]:
    """Absolute paths of the files this repo's install command reads.

    Delegates to `environment.discover_files`, which searches one directory
    deep. The previous root-only version returned [] for any repo keeping its
    manifests in `backend/` or `frontend/`, so the build context held nothing
    but the generated Dockerfile.
    """
    return [root / rel for rel in discover_files(root)]


def manifest_hash(root: Path, install_cmd: str, spec: EnvironmentSpec | None = None) -> str:
    """Identity of the environment.

    Covers the manifests, the command that reads them, AND the resolved system
    packages — otherwise changing the package set would silently reuse an image
    built without it.
    """
    resolved = spec or resolve_environment(root, install_cmd)
    digest = hashlib.sha256()
    digest.update(install_cmd.encode())
    digest.update(resolved.identity().encode())
    for rel in resolved.copy_paths:
        digest.update(str(rel).encode())
        try:
            digest.update((root / rel).read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    return digest.hexdigest()[:16]


def image_tag(
    repo_id: str, root: Path, install_cmd: str, spec: EnvironmentSpec | None = None
) -> str:
    return f"aso-prepared:{repo_id[:12]}-{manifest_hash(root, install_cmd, spec)}"


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

    # Nothing to cache: the runtime bind-mount over /workspace would hide
    # whatever this wrote. The caller runs it as a normal in-container step
    # instead, where the test step can see the result.
    if installs_into_workspace(install_cmd):
        log.info(
            "skipping prepared image: install writes into the workspace",
            extra={"install": install_cmd},
        )
        return base, None

    spec = resolve_environment(root, install_cmd)
    tag = image_tag(repo_id, root, install_cmd, spec)
    with _lock_for(tag):
        if _image_exists(tag):
            return tag, None

        start = time.monotonic()
        context = Path(tempfile.mkdtemp(prefix="aso-prep-"))
        try:
            # Structure preserved. Copying to `path.name` flattened
            # backend/pyproject.toml to pyproject.toml, so an install command
            # that begins `cd backend` could never find it.
            for rel in spec.copy_paths:
                target = context / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / rel, target)

            apt = ""
            if spec.system_packages:
                packages = " ".join(spec.system_packages)
                apt = (
                    "RUN apt-get update && apt-get install -y --no-install-recommends "
                    f"{packages} && rm -rf /var/lib/apt/lists/*\n"
                )
            (context / "Dockerfile").write_text(
                f"FROM {base}\n"
                "USER root\n"
                "WORKDIR /workspace\n"
                f"{apt}"
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

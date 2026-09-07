"""Bounded repository digest for AI-assisted setup.

This is the ONLY place in the product that sends repository content to a third
party — agent sandboxes are sealed and reach nothing but the model proxy. So
the rule here is an **allowlist**: only files that plausibly describe how a
project is built or tested are ever read. A blocklist would leak the first
secret nobody thought to name.

Everything is bounded (file count, per-file bytes, total characters) so the
prompt stays cheap and inside a small model's context.
"""

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

# Only these are read. Anything not matching is listed by name at most.
MANIFEST_PATTERNS = (
    "README*",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements*.txt",
    "Pipfile",
    "tox.ini",
    "pytest.ini",
    "package.json",
    "Makefile",
    "justfile",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle*",
    "Gemfile",
    "composer.json",
    "Dockerfile*",
    "*.cabal",
)
CI_DIRS = (".github/workflows",)

# Never walked at all.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", "target", "vendor",
    ".idea", ".vscode", "coverage", ".tox",
}

# Belt-and-braces on top of the allowlist: even if one of these somehow matched
# a manifest pattern, it is never read and never named.
SECRET_PATTERNS = (
    ".env*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
    "*credential*", "*secret*", "*.keystore", ".npmrc", ".pypirc", ".netrc",
)

MAX_TREE_ENTRIES = 400
MAX_FILE_CHARS = 3000
MAX_README_CHARS = 4000
MAX_TOTAL_CHARS = 24_000
MAX_COMMITS = 25

# Grading reads the cited source, which is a bigger per-file budget than setup
# analysis needs: a criterion about a call order is only checkable against the
# function itself. Sized so six criteria over three or four distinct modules
# fit alongside the answer (24k) without crowding the judge's context.
MAX_EVIDENCE_FILE_CHARS = 6_000
MAX_EVIDENCE_TOTAL_CHARS = 30_000


def is_secret(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, p) for p in SECRET_PATTERNS)


def _is_manifest(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in MANIFEST_PATTERNS)


@dataclass
class Digest:
    tree: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    commits: list[dict[str, str]] = field(default_factory=list)
    truncated: bool = False

    def as_prompt_text(self) -> str:
        parts = [f"FILE TREE ({len(self.tree)} paths shown):", *self.tree, ""]
        for path, content in self.files.items():
            parts += [f"--- {path} ---", content, ""]
        if self.commits:
            parts.append("RECENT COMMITS:")
            parts += [f"{c['sha'][:8]} {c['subject']}" for c in self.commits]
        return "\n".join(parts)[:MAX_TOTAL_CHARS]


def read_evidence(root: Path, paths: list[str]) -> dict[str, str]:
    """Source of the files a rubric criterion cites, for grading.

    Deliberately here rather than in the evaluator: this module owns the rule
    about what may leave the machine, and grading needs a WIDER set than
    `build_digest`'s manifest allowlist — a criterion about a call order cites
    the module that implements it, not a README.

    That widening is the point. Without it the judge sees only paths and can
    check that an answer names real files and covers the rubric's topics, never
    whether a single claim about those files is true.

    Still bounded and still secret-safe: resolved inside `root` so a crafted
    path cannot escape the repository, refused for anything matching
    SECRET_PATTERNS, and capped per file and in total.
    """
    out: dict[str, str] = {}
    budget = MAX_EVIDENCE_TOTAL_CHARS
    root = root.resolve()
    for rel in dict.fromkeys(p.strip().lstrip("./") for p in paths if p and p.strip()):
        if budget <= 0:
            break
        candidate = (root / rel).resolve()
        if not candidate.is_relative_to(root) or is_secret(candidate.name):
            continue
        if not candidate.is_file():
            continue
        content = _read(candidate, min(MAX_EVIDENCE_FILE_CHARS, budget))
        if content:
            out[rel] = content
            budget -= len(content)
    return out


def _read(path: Path, limit: int) -> str | None:
    try:
        return path.read_text(errors="replace")[:limit]
    except (OSError, UnicodeDecodeError):
        return None


def build_digest(root: Path, commits: list[dict[str, str]] | None = None) -> Digest:
    """Walk `root` and collect only what describes how to build and test it."""
    digest = Digest(commits=(commits or [])[:MAX_COMMITS])

    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if not path.is_file() or is_secret(path.name):
            continue

        rel = str(path.relative_to(root))
        if len(digest.tree) < MAX_TREE_ENTRIES:
            digest.tree.append(rel)
        else:
            digest.truncated = True

        in_ci = any(rel.startswith(d) for d in CI_DIRS)
        if _is_manifest(path.name) or in_ci:
            limit = MAX_README_CHARS if path.name.lower().startswith("readme") else MAX_FILE_CHARS
            content = _read(path, limit)
            if content is not None:
                digest.files[rel] = content

    return digest

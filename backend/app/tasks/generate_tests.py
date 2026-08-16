"""Generate a hidden test when the solution commit does not ship one.

`extract_hidden_tests` only works when the commit itself added tests. A repo that
fixes behaviour without touching its suite leaves the benchmark grading against
whatever tests already exist — and on a repo whose tests are three bare `pass`
statements, that cannot separate a correct patch from an empty one. Every model
then scores the same and the ranking is noise.

Nothing here is trusted on the model's word. A generated test is worthless
unless it discriminates, so each candidate must FAIL at the parent commit and
PASS at the solution commit before it is offered for approval. Those two runs
are the entire point of this module: they are the difference between a test and
a plausible-looking string.

The diff IS the answer, and it is only ever read here, at setup time. It never
reaches the agent — see `historical.commit_task_description`.
"""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.providers.base import ModelProvider

# First attempt plus two regenerations. A model that cannot write a
# discriminating test in three tries is not going to find it in ten, and each
# attempt costs two container runs.
MAX_ATTEMPTS = 3

# Generated content is capped before it reaches a model or a disk: a diff can be
# megabytes, and the useful signal is at the top of it.
MAX_DIFF_CHARS = 24_000
MAX_SAMPLE_CHARS = 4_000


SYSTEM = """You write ONE pytest file that proves whether a specific bug fix is present.

You are shown the diff of a commit that fixed a bug. Write a test that:
- FAILS when run against the code BEFORE that commit, and
- PASSES when run against the code AFTER it.

That pair is the only thing that matters. A test that passes both ways is
useless and will be discarded; so is one that fails both ways.

Rules:
- Reply with ONE ```python fenced block and nothing else outside it.
- Test the BEHAVIOUR the diff changed, through the module's public surface.
  Do not assert on the diff's exact wording, line numbers or private names.
- The file MUST import cleanly at BOTH commits. If you need a symbol that only
  exists after the fix, import it INSIDE the test function, not at module top —
  a module-level ImportError breaks collection for the whole suite and the
  candidate is rejected.
- No network, no sleeps, no randomness, no reading files outside the repo.
- Name every test function `test_*`. Keep the whole file under 80 lines.
- If the diff is purely cosmetic (docs, formatting, imports, version bumps) and
  no behavioural test is possible, reply with exactly: NO_BEHAVIOURAL_CHANGE"""


NO_TEST_SENTINEL = "NO_BEHAVIOURAL_CHANGE"

_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


class GenerationError(Exception):
    """The model did not return usable test source. Worth another attempt."""


class NoBehaviouralChange(GenerationError):
    """The commit has nothing testable — retrying cannot change the diff.

    Distinct from GenerationError because the retry policy differs, and getting
    that wrong is expensive in both directions: retrying a docs-only commit
    burns three calls for nothing, while giving up on one empty reply throws
    away a testable commit on a single bad roll.
    """


@dataclass
class GeneratedTest:
    """A candidate and the evidence for or against it."""

    relpath: str
    content: str
    verified: bool = False
    reject_reason: str | None = None
    attempts: int = 0
    # Per-case outcomes at each commit, so a rejection can be explained rather
    # than asserted. Empty when the candidate never got as far as running.
    evidence: dict[str, Any] = field(default_factory=dict)


class BaselineRunner(Protocol):
    """Injected so tests can exercise the gate without Docker."""

    def __call__(
        self,
        workspace: Path,
        commands: dict[str, str | None],
        test_framework: str | None,
        repo_id: str,
    ) -> Any: ...


def extract_test_source(text: str) -> str:
    """Pull the python block out of a reply, or say why there isn't one."""
    if NO_TEST_SENTINEL in text:
        raise NoBehaviouralChange(
            "model reports the commit has no behavioural change to test"
        )
    match = _FENCE.search(text)
    body = match.group(1) if match else text
    body = body.strip()
    if not body:
        raise GenerationError("model returned an empty test file")
    if "def test" not in body:
        raise GenerationError("model returned no test function")
    return body + "\n"


def generated_relpath(target_sha: str, near: str | None) -> str:
    """Where the candidate lands — chosen by us, never by the model.

    A fixed, unique basename is what makes verification possible: pytest case
    ids are `path::name`, so the stem identifies exactly the cases this file
    contributed and nothing else. Letting the model pick would also let it
    overwrite a real test file.
    """
    stem = f"test_aso_generated_{target_sha[:7]}"
    parent = Path(near).parent if near else Path("tests")
    return str(parent / f"{stem}.py")


def build_messages(
    diff: str, subject: str, framework: str | None, style_sample: str | None
) -> list[dict[str, Any]]:
    parts = [
        f"Commit subject: {subject}",
        f"Test framework: {framework or 'pytest'}",
        "",
        "--- diff of the fix ---",
        diff[:MAX_DIFF_CHARS],
        "--- end diff ---",
    ]
    if style_sample:
        parts += [
            "",
            "An existing test from this repository, for style and import paths only:",
            "",
            style_sample[:MAX_SAMPLE_CHARS],
        ]
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n".join(parts)},
    ]


async def generate_test_source(
    provider: ModelProvider,
    model_id: str,
    diff: str,
    subject: str,
    framework: str | None,
    style_sample: str | None,
    nudge: str | None = None,
) -> str:
    """One model call. `nudge` carries why the previous attempt was rejected."""
    messages = build_messages(diff, subject, framework, style_sample)
    if nudge:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Your previous attempt was rejected: {nudge}\n"
                    "Write a different test that satisfies the fail-then-pass requirement."
                ),
            }
        )
    # Generous because reasoning models bill their thinking against this cap
    # before a single character of the file is emitted: at 1600, gpt-5.6-sol
    # returned an empty body for a test that fits comfortably in 40 lines.
    result = await provider.complete(model_id, messages, temperature=0.0, max_tokens=6000)
    return extract_test_source(result.content)


def _cases_from(outcome: Any, stem: str) -> list[tuple[str, str]]:
    """Only the cases this generated file contributed."""
    return [(cid, res) for cid, res in getattr(outcome, "test_cases", []) if stem in cid]


def _run_with_test(
    root: Path,
    commit: str,
    relpath: str,
    content: str,
    commands: dict[str, str | None],
    framework: str | None,
    repo_id: str,
    run_baseline: BaselineRunner,
) -> Any:
    """Snapshot at `commit`, drop the candidate in, run the suite."""
    workdir = Path(tempfile.mkdtemp(prefix="aso-gentest-"))
    snapshot = workdir / "snapshot"
    try:
        from app.repositories import service

        service.create_snapshot(root, commit, snapshot)
        target = snapshot / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return run_baseline(snapshot, dict(commands), framework, repo_id)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def verify_generated_test(
    root: Path,
    parent: str,
    target: str,
    relpath: str,
    content: str,
    commands: dict[str, str | None],
    framework: str | None,
    repo_id: str,
    run_baseline: BaselineRunner | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Fail at the parent, pass at the solution. Returns (ok, reason, evidence).

    Checked per CASE, not per exit code: the suite contains other tests, and a
    non-zero exit tells you nothing about which one failed.

    A candidate that does not appear at all at the parent commit is rejected
    rather than assumed to have failed — the usual cause is a module-level
    import of something that only exists after the fix, which breaks collection
    for the entire suite and would corrupt the graded run.
    """
    if run_baseline is None:
        from app.sandboxes.runner import run_baseline_in_sandbox

        run_baseline = run_baseline_in_sandbox

    stem = Path(relpath).stem
    evidence: dict[str, Any] = {}

    before = _run_with_test(
        root, parent, relpath, content, commands, framework, repo_id, run_baseline
    )
    before_cases = _cases_from(before, stem)
    evidence["at_parent"] = before_cases
    if not before_cases:
        return (
            False,
            "test did not run at the parent commit — it likely fails to import there",
            evidence,
        )
    if any(res == "passed" for _, res in before_cases):
        return (
            False,
            "test already passes on the unfixed code, so it cannot detect the bug",
            evidence,
        )

    after = _run_with_test(
        root, target, relpath, content, commands, framework, repo_id, run_baseline
    )
    after_cases = _cases_from(after, stem)
    evidence["at_solution"] = after_cases
    if not after_cases:
        return False, "test did not run at the solution commit", evidence
    if not all(res == "passed" for _, res in after_cases):
        return False, "test does not pass even on the fixed code, so it is wrong", evidence

    return True, "", evidence


def commit_diff(root: Path, parent: str, target: str) -> str:
    proc = subprocess.run(
        ["git", "diff", parent, target],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise GenerationError(f"could not diff {parent[:8]}..{target[:8]}: {proc.stderr[:200]}")
    return proc.stdout


def find_style_sample(root: Path) -> tuple[str | None, str | None]:
    """An existing test file, as (relpath, content), for style and import paths."""
    from app.tasks.historical import is_test_file

    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        if is_test_file(rel) and ".git" not in rel:
            try:
                return rel, path.read_text(errors="replace")
            except OSError:
                continue
    return None, None


async def generate_verified_test(
    provider: ModelProvider,
    model_id: str,
    root: Path,
    parent: str,
    target: str,
    subject: str,
    commands: dict[str, str | None],
    framework: str | None,
    repo_id: str,
    run_baseline: BaselineRunner | None = None,
) -> GeneratedTest:
    """Generate, prove, and retry. Returns the survivor or the last rejection.

    A rejected candidate is returned rather than swallowed: "no test could be
    generated" with no reason is how a benchmark quietly goes back to scoring
    against tests that cannot fail.
    """
    diff = commit_diff(root, parent, target)
    sample_path, sample = find_style_sample(root)
    relpath = generated_relpath(target, sample_path)

    last = GeneratedTest(relpath=relpath, content="", reject_reason="no attempt was made")
    nudge: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content = await generate_test_source(
                provider, model_id, diff, subject, framework, sample, nudge
            )
        except NoBehaviouralChange as exc:
            # A model that declines to test a docs-only commit is answering
            # correctly; retrying cannot change the diff.
            return GeneratedTest(
                relpath=relpath, content="", reject_reason=str(exc), attempts=attempt
            )
        except GenerationError as exc:
            # An empty or malformed reply is a bad roll, not a verdict. Measured
            # against gpt-5.6-sol: the first attempt came back empty and one
            # retry is cheap next to throwing away a testable commit.
            last = GeneratedTest(
                relpath=relpath, content="", reject_reason=str(exc), attempts=attempt
            )
            nudge = str(exc)
            continue

        ok, reason, evidence = verify_generated_test(
            root, parent, target, relpath, content, commands, framework, repo_id, run_baseline
        )
        last = GeneratedTest(
            relpath=relpath,
            content=content,
            verified=ok,
            reject_reason=None if ok else reason,
            attempts=attempt,
            evidence=evidence,
        )
        if ok:
            return last
        nudge = reason

    return last

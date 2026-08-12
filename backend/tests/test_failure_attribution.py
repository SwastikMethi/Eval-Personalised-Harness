"""A sandbox fault is not a harness fault.

Harness reliability is the product's central metric, so what gets booked
against a harness decides which stack the tool recommends. Every exception on
the run path used to be recorded as ErrorCategory.HARNESS, so a container
Docker killed, a network that vanished, and a failed seal all read as harness
crashes — mini-swe-agent looked unreliable largely because of infrastructure it
neither caused nor could have prevented.
"""

from types import SimpleNamespace

from app.core.errors import ErrorCategory
from app.harnesses.base import probe_failed
from app.orchestration.queue import _category_for
from app.sandboxes.manager import SandboxError


def test_sandbox_failure_is_setup_not_harness() -> None:
    assert _category_for(SandboxError("container exited before the command")) == (
        ErrorCategory.SETUP
    )


def test_docker_api_failure_is_setup_not_harness() -> None:
    """The 409 'container is not running' and 404 'network not found' seen in
    a real batch — Docker's fault, not the agent's."""
    from docker.errors import APIError, NotFound

    assert _category_for(APIError("409 Client Error: container is not running")) == (
        ErrorCategory.SETUP
    )
    assert _category_for(NotFound("404 Client Error: network not found")) == ErrorCategory.SETUP


def test_a_real_harness_crash_is_still_harness() -> None:
    """Accuracy in both directions: this must not become a blanket excuse."""
    assert _category_for(RuntimeError("harness protocol error")) == ErrorCategory.HARNESS
    assert _category_for(ValueError("bad harness output")) == ErrorCategory.HARNESS


def test_probe_claims_absence_only_when_the_output_says_so() -> None:
    missing = SimpleNamespace(exit_code=127, stdout="", stderr="sh: mini: command not found")
    err = probe_failed("the mini-swe-agent CLI", "mini --help", missing)
    assert "not installed in the sandbox image" in str(err)

    no_module = SimpleNamespace(
        exit_code=1, stdout="", stderr="ModuleNotFoundError: No module named 'smolagents'"
    )
    assert "not installed in the sandbox image" in str(probe_failed("smolagents", "x", no_module))


def test_probe_does_not_blame_the_image_when_it_simply_could_not_run() -> None:
    """The false message that sent this session chasing an image problem: the
    container was dying, and the probe reported a missing dependency."""
    dying = SimpleNamespace(exit_code=137, stdout="", stderr="")
    err = probe_failed("the mini-swe-agent CLI", "mini --help", dying)

    assert "not installed" not in str(err)
    assert "sandbox failure" in str(err)
    # Still filed as SETUP, so it never lands on the harness's record.
    assert _category_for(err) == ErrorCategory.SETUP

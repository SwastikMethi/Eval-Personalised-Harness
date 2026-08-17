"""Tasks share a run when, and only when, they need the same workspace.

Three stacks and two comprehension questions used to produce six runs: six
clones of the same repository at the same commit, six containers, and the agent
re-exploring the same codebase to answer the second question.

The limit is not a preference. A commit replay is reconstructed at its own
commit's parent, so two of them need two different trees — grouping those would
grade one task against a tree built for another.
"""

from dataclasses import dataclass

from app.orchestration.snapshot_key import describe_grouping, group_tasks, snapshot_key


@dataclass(frozen=True)
class Task:
    id: str
    kind: str = "theory"
    repository_id: str | None = "repo1"
    base_commit: str | None = None


def test_comprehension_tasks_on_one_repo_share_a_snapshot() -> None:
    a, b = Task("a"), Task("b")
    assert snapshot_key(a) == snapshot_key(b)
    assert group_tasks([a, b]) == [["a", "b"]]


def test_comprehension_tasks_on_different_repos_do_not() -> None:
    a = Task("a", repository_id="repo1")
    b = Task("b", repository_id="repo2")
    assert group_tasks([a, b]) == [["a"], ["b"]]


def test_commit_replays_with_different_parents_stay_separate() -> None:
    """The property the whole rule exists for: no tree is both 'before A' and
    'before B'."""
    a = Task("a", kind="commit", base_commit="parent-a")
    b = Task("b", kind="commit", base_commit="parent-b")
    assert group_tasks([a, b]) == [["a"], ["b"]]


def test_commit_replays_sharing_a_parent_do_group() -> None:
    a = Task("a", kind="commit", base_commit="same")
    b = Task("b", kind="commit", base_commit="same")
    assert group_tasks([a, b]) == [["a", "b"]]


def test_a_mixed_selection_groups_what_it_can() -> None:
    """2 comprehension + 2 commit → 3 groups, not 1 and not 4."""
    groups = group_tasks(
        [
            Task("t1"),
            Task("c1", kind="commit", base_commit="p1"),
            Task("t2"),
            Task("c2", kind="commit", base_commit="p2"),
        ]
    )
    assert groups == [["t1", "t2"], ["c1"], ["c2"]]


def test_a_commit_task_keys_on_its_parent_even_if_marked_theory() -> None:
    """base_commit wins, mirroring _prepare_workspace. If these disagreed a run
    would be built at a snapshot its tasks were not grouped for."""
    task = Task("x", kind="theory", base_commit="parent")
    assert snapshot_key(task).startswith("commit:")


def test_a_task_with_no_buildable_snapshot_stands_alone() -> None:
    """It cannot run; failing alone names one task instead of taking a group."""
    a = Task("a", kind="user_defined", base_commit=None)
    b = Task("b", kind="user_defined", base_commit=None)
    assert group_tasks([a, b]) == [["a"], ["b"]]


def test_fixture_tasks_group_by_fixture() -> None:
    config = {"fixture_path": "/fixtures/python-bug-repo"}
    a = Task("a", kind="user_defined")
    b = Task("b", kind="user_defined")
    assert group_tasks([a, b], config) == [["a", "b"]]


def test_grouping_preserves_selection_order() -> None:
    groups = group_tasks([Task("c1", kind="commit", base_commit="p"), Task("t1")])
    assert groups == [["c1"], ["t1"]]


def test_the_explanation_says_why_a_split_happened() -> None:
    assert "own sandbox" in describe_grouping([["a"], ["b"]])
    mixed = describe_grouping([["t1", "t2"], ["c1"]])
    assert "share one sandbox" in mixed
    assert "own snapshot" in mixed


# --- a grouped run must not lose a task's score -----------------------------


def test_a_grouped_run_reports_one_sample_per_task() -> None:
    """Two answers from one run stay two scores.

    Results used to take the newest evaluation for a run and stamp it with the
    combination's task_id. For a grouped run that dropped every task but one
    and filed its score under the group's first task.
    """
    from app.api.results_api import _samples
    from app.db.engine import SessionLocal, ensure_schema
    from app.models import (
        BenchmarkRun,
        BenchmarkTask,
        EvaluationResult,
        Experiment,
        ExperimentCombination,
        Repository,
    )

    ensure_schema()
    with SessionLocal() as session:
        repo = Repository(name="r", source="local", path_or_url="/tmp/r")
        session.add(repo)
        session.flush()
        t1 = BenchmarkTask(repository_id=repo.id, kind="theory", title="q1", prompt="p")
        t2 = BenchmarkTask(repository_id=repo.id, kind="theory", title="q2", prompt="p")
        exp = Experiment(repository_id=repo.id, name="e", repetitions=1, config={})
        session.add_all([t1, t2, exp])
        session.flush()
        combo = ExperimentCombination(
            experiment_id=exp.id,
            task_id=t1.id,
            task_ids=[t1.id, t2.id],
            harness="fake",
            provider="fake",
            model_id="m",
        )
        session.add(combo)
        session.flush()
        run = BenchmarkRun(
            combination_id=combo.id,
            repetition=1,
            idempotency_key=f"{combo.id}-1",
            state="COMPLETED",
            result={},
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                EvaluationResult(run_id=run.id, task_id=t1.id, signal="ok", score=0.8),
                EvaluationResult(run_id=run.id, task_id=t2.id, signal="ok", score=0.2),
            ]
        )
        session.flush()

        samples = _samples(session, exp.id)
        by_task = {s.task_id: s.score for s in samples}

    assert by_task == {t1.id: 0.8, t2.id: 0.2}

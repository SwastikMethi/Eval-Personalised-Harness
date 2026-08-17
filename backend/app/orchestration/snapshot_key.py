"""Which tasks can share one sandbox.

A run used to be one task, so three stacks and two comprehension questions
produced six runs: six clones of the same repository at the same commit, six
containers, and the agent re-exploring the same codebase to answer a second
question about it.

Tasks can share a run when they need the same workspace, and only then. That is
a property of the snapshot, not a preference:

  - a comprehension task reads the repository as it stands, so every one of them
    wants HEAD and they group;
  - a commit replay is reconstructed at its own commit's parent, so two of them
    want two different trees. No single workspace is both "before commit A" and
    "before commit B", and grouping them would silently grade one task against a
    tree built for another.

The branching below mirrors `queue._prepare_workspace` deliberately. If the two
ever disagree, a run is built at a snapshot its tasks were not grouped for, so
they are kept side by side rather than inferred from each other.
"""

from collections.abc import Iterable, Sequence
from typing import Any, Protocol


class _TaskLike(Protocol):
    """Structural, so this module does not import the ORM models.

    Read-only properties rather than plain attributes: mutable protocol members
    match invariantly, so `repository_id: str | None` here would reject a model
    declaring `Mapped[str]`.
    """

    @property
    def id(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def repository_id(self) -> str | None: ...

    @property
    def base_commit(self) -> str | None: ...


def snapshot_key(task: _TaskLike, config: dict[str, Any] | None = None) -> str:
    """Identity of the workspace this task needs.

    Two tasks with the same key can be answered in one sandbox.
    """
    # Order matches _prepare_workspace: base_commit wins, then theory, then a
    # fixture. A commit task that is also somehow theory is still reconstructed
    # at its parent, so it must key that way.
    if task.base_commit:
        return f"commit:{task.base_commit}"
    if task.kind == "theory":
        return f"head:{task.repository_id}"
    fixture = (config or {}).get("fixture_path")
    if fixture:
        return f"fixture:{fixture}"
    # No snapshot can be built for this task; let it stand alone so the run that
    # fails names one task rather than taking a group down with it.
    return f"task:{task.id}"


def group_tasks(
    tasks: Sequence[_TaskLike], config: dict[str, Any] | None = None
) -> list[list[str]]:
    """Task ids grouped by the workspace they need, in first-seen order.

    Order is preserved rather than sorted so the groups, and the runs made from
    them, follow the order the tasks were selected in.
    """
    groups: dict[str, list[str]] = {}
    for task in tasks:
        groups.setdefault(snapshot_key(task, config), []).append(task.id)
    return list(groups.values())


def describe_grouping(groups: Iterable[Sequence[str]]) -> str:
    """One sentence for the UI about why the run count is what it is."""
    sizes = [len(g) for g in groups]
    shared = sum(1 for n in sizes if n > 1)
    if not shared:
        return "Each task runs in its own sandbox."
    largest = max(sizes)
    tail = (
        " Each commit replay needs its own snapshot, so those are not grouped."
        if any(n == 1 for n in sizes)
        else ""
    )
    return (
        f"{largest} tasks share one sandbox because they read the same snapshot.{tail}"
    )


__all__ = ["describe_grouping", "group_tasks", "snapshot_key"]

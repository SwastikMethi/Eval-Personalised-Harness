"""task groups: combination task_ids, evaluation task_id

A run used to be one task. Tasks that need the same repository snapshot now
share one run and one sandbox, so a combination carries a list and an
evaluation records which task its score belongs to.

Revision ID: 747a6046b707
Revises: bca773b06c54
Create Date: 2026-08-17 16:18:52.161108

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "747a6046b707"
down_revision: str | Sequence[str] | None = "bca773b06c54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation_results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_id", sa.String(), nullable=True))
        # Named, or the downgrade cannot drop it on SQLite.
        batch_op.create_foreign_key(
            "fk_evaluation_results_task_id", "benchmark_tasks", ["task_id"], ["id"]
        )

    # server_default, not a bare NOT NULL: autogenerate proposed the latter,
    # which cannot be applied to a table that already has rows.
    with op.batch_alter_table("experiment_combinations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("task_ids", sa.JSON(), nullable=False, server_default="[]")
        )

    # Existing combinations each covered exactly one task. Carry it into the
    # list so historical experiments keep resolving instead of reading as
    # covering no tasks at all.
    op.execute(
        "UPDATE experiment_combinations "
        "SET task_ids = json_array(task_id) "
        "WHERE task_ids IS NULL OR task_ids = '[]'"
    )

    # Likewise, every existing evaluation belongs to its combination's one task.
    op.execute(
        "UPDATE evaluation_results SET task_id = ("
        "  SELECT c.task_id FROM benchmark_runs r"
        "  JOIN experiment_combinations c ON c.id = r.combination_id"
        "  WHERE r.id = evaluation_results.run_id"
        ") WHERE task_id IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("experiment_combinations", schema=None) as batch_op:
        batch_op.drop_column("task_ids")

    with op.batch_alter_table("evaluation_results", schema=None) as batch_op:
        batch_op.drop_constraint("fk_evaluation_results_task_id", type_="foreignkey")
        batch_op.drop_column("task_id")

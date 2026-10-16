"""给抓取任务增加独立新增数量。"""
from alembic import op
import sqlalchemy as sa

revision = "0002_crawl_task_new_count"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "new_count" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("crawl_tasks")}:
        op.add_column("crawl_tasks", sa.Column("new_count", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("crawl_tasks", "new_count")

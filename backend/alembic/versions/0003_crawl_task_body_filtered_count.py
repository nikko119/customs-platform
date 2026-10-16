"""记录正文关键词筛除数量。"""
from alembic import op
import sqlalchemy as sa

revision = "0003_crawl_task_body_filtered_count"
down_revision = "0002_crawl_task_new_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "body_filtered_count" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("crawl_tasks")}:
        op.add_column("crawl_tasks", sa.Column("body_filtered_count", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("crawl_tasks", "body_filtered_count")

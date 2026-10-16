"""记录抓取任务采用的自动/手动模式。"""
from alembic import op
import sqlalchemy as sa

revision = "0007_crawl_task_mode"
down_revision = "0006_prompt_purpose"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("crawl_tasks")}
    if "crawl_mode" not in columns:
        op.add_column("crawl_tasks", sa.Column("crawl_mode", sa.String(30), server_default="MANUAL", nullable=False))
    if "date_filtered_count" not in columns:
        op.add_column("crawl_tasks", sa.Column("date_filtered_count", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("crawl_tasks", "date_filtered_count")
    op.drop_column("crawl_tasks", "crawl_mode")

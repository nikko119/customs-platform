"""为原始新闻增加独立的清洗结果字段。"""
from alembic import op
import sqlalchemy as sa

revision = "0004_article_cleaned_content"
down_revision = "0003_crawl_task_body_filtered_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "cleaned_content" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("news_articles")}:
        op.add_column("news_articles", sa.Column("cleaned_content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("news_articles", "cleaned_content")

"""区分翻译模板和改写模板。"""
from alembic import op
import sqlalchemy as sa

revision = "0006_prompt_purpose"
down_revision = "0005_article_translations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "purpose" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("prompts")}:
        op.add_column("prompts", sa.Column("purpose", sa.String(20), server_default="REWRITE", nullable=False))


def downgrade() -> None:
    op.drop_column("prompts", "purpose")

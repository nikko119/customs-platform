"""保存独立译文，并将改写结果和任务关联到译文阶段。"""
from alembic import op
import sqlalchemy as sa

revision = "0005_article_translations"
down_revision = "0004_article_cleaned_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 早期初始迁移按当时运行的模型建表；新安装已包含译文表和关联字段。
    if "news_translations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "news_translations",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("article_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), nullable=False),
        sa.Column("source_language", sa.String(10), server_default="en", nullable=False),
        sa.Column("target_language", sa.String(10), server_default="zh-CN", nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("translated_content", sa.Text(), nullable=False),
        sa.Column("translation_status", sa.String(20), server_default="MOCK", nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(191), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["news_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_translation_article_created", "news_translations", ["article_id", "created_at"])
    with op.batch_alter_table("news_processed") as batch_op:
        batch_op.add_column(sa.Column("translation_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), nullable=True))
        batch_op.create_foreign_key("fk_news_processed_translation", "news_translations",
                                    ["translation_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("llm_tasks") as batch_op:
        batch_op.add_column(sa.Column("task_type", sa.String(20), server_default="REWRITE", nullable=False))
        batch_op.add_column(sa.Column("translation_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), nullable=True))
        batch_op.create_foreign_key("fk_llm_tasks_translation", "news_translations",
                                    ["translation_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("llm_tasks") as batch_op:
        batch_op.drop_constraint("fk_llm_tasks_translation", type_="foreignkey")
        batch_op.drop_column("translation_id")
        batch_op.drop_column("task_type")
    with op.batch_alter_table("news_processed") as batch_op:
        batch_op.drop_constraint("fk_news_processed_translation", type_="foreignkey")
        batch_op.drop_column("translation_id")
    op.drop_index("ix_translation_article_created", table_name="news_translations")
    op.drop_table("news_translations")

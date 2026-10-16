from sqlalchemy import create_engine, inspect
from app.models import Article, ArticleImage, Base


def test_database_schema_can_create_on_sqlite():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"countries", "source_sites", "news_articles", "news_images", "prompts", "news_processed", "crawl_tasks", "llm_tasks"} <= tables


def test_sqlite_bigint_ids_are_unique_for_multiple_images():
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        article = Article(
            source_site_id=1, normalized_url="https://example.test/article",
            source_url="https://example.test/article", title="Test", content="Body",
            content_hash="a" * 64,
        )
        # 这里只验证编号分配钩子，外键约束在 SQLite 默认关闭。
        article.images = [
            ArticleImage(original_url="https://example.test/1.jpg", position=0),
            ArticleImage(original_url="https://example.test/2.jpg", position=1),
        ]
        db.add(article)
        db.commit()
        assert article.id is not None
        assert [image.id for image in article.images] == [1, 2]

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Article, Base, Country, SourceSite
from app.services.article_persistence import ensure_cbp_source, upsert_crawled_article
from crawlers.cbp import Article as CrawledArticle, ArticleImage


def make_article(content: str) -> CrawledArticle:
    from crawlers.cbp import content_hash
    return CrawledArticle(
        country="US", site="CBP", source_url="https://www.cbp.gov/newsroom/test-story",
        title="Test story", author=None, published_at="Wed, 10/07/2026", language="en",
        content=content, content_hash=content_hash(content),
        images=[ArticleImage("https://www.cbp.gov/test.jpg", "data/images/test.jpg", "test", 0)],
        crawl_status="SUCCESS", crawled_at=datetime.now().isoformat(),
    )


def test_article_upsert_new_updated_unchanged_and_images():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        site = ensure_cbp_source(db)
        assert upsert_crawled_article(db, site, make_article("first body")) == "NEW"
        db.commit()
        assert upsert_crawled_article(db, site, make_article("first body")) == "UNCHANGED"
        db.commit()
        assert upsert_crawled_article(db, site, make_article("changed body")) == "UPDATED"
        db.commit()
        article = db.scalar(select(Article))
        assert article.content == "changed body"
        assert len(article.images) == 1

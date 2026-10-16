import asyncio
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Article, Base, Country, CrawlTask, SourceSite
from crawlers.runner import run_managed_site_crawl
from crawlers.site import SiteAdapter


def test_new_site_reuses_task_and_article_persistence(monkeypatch, tmp_path: Path):
    import crawlers.runner as runner

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "SessionLocal", sessions)
    with sessions() as db:
        country = Country(code="CA", name="Canada")
        db.add(country); db.flush()
        site = SourceSite(country_id=country.id, site_code="CBSA", name="CBSA",
                          base_url="https://cbsa.test", list_url="https://cbsa.test/news")
        db.add(site); db.commit()
        site_id = site.id

    adapter = SiteAdapter(
        country="CA", site="CBSA", list_url="https://cbsa.test/news", keywords=("cargo",),
        parse_listing=lambda html, url: [], parse_article=lambda html, url: None,
        normalize_url=lambda url, base: url, page_url=lambda page: "https://cbsa.test/news",
        matches_body=lambda text, keywords: True,
    )

    async def fake_crawl(site_adapter, options, callbacks):
        assert site_adapter.site == "CBSA"
        assert options.crawl_mode == "MANUAL"
        article = SimpleNamespace(source_url="https://cbsa.test/story/1", title="Cargo update",
                                  author=None, published_at="2026-10-16", language="en",
                                  content="Cargo arrived", content_hash="a" * 64,
                                  crawl_status="SUCCESS", images=[])
        assert callbacks.persist_article(article, "raw.html") == "NEW"
        assert callbacks.persist_article(article, "raw.html") == "UNCHANGED"
        return {"discovered": 1, "selected": 1, "filtered": 0, "date_filtered": 0,
                "pages_visited": 1, "crawl_mode": options.crawl_mode, "body_filtered": 0,
                "success": 2, "new": 1, "updated": 0, "unchanged": 1, "errors": []}

    monkeypatch.setattr(runner, "run_site_crawl", fake_crawl)
    summary = asyncio.run(run_managed_site_crawl(adapter, site_id, output_dir=tmp_path, max_pages=1))
    with sessions() as db:
        article = db.scalar(select(Article))
        task = db.get(CrawlTask, summary["task_id"])
        assert article.source_site_id == site_id
        assert task.source_site_id == site_id
        assert task.status == "SUCCESS" and task.new_count == 1 and task.unchanged_count == 1

    bad_adapter = SiteAdapter(**{**adapter.__dict__, "site": "WRONG"})
    try:
        asyncio.run(run_managed_site_crawl(bad_adapter, site_id, output_dir=tmp_path))
    except ValueError as exc:
        assert "不匹配" in str(exc)
    else:
        raise AssertionError("站点与适配器不一致时应拒绝运行")

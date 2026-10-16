from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import (Article, ArticleImage, ArticleTranslation, Base, Country,
                        ProcessedArticle, PromptTemplate, SourceSite)


def client_with_data():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), sessions


def test_export_latest_real_current_rewrite_with_filters_and_pagination():
    client, sessions = client_with_data()
    with sessions() as db:
        us = Country(code="US", name="United States")
        ca = Country(code="CA", name="Canada")
        db.add_all([us, ca]); db.flush()
        cbp = SourceSite(country_id=us.id, site_code="CBP", name="CBP",
                         base_url="https://cbp.test", list_url="https://cbp.test/news")
        cbsa = SourceSite(country_id=ca.id, site_code="CBSA", name="CBSA",
                          base_url="https://cbsa.test", list_url="https://cbsa.test/news")
        db.add_all([cbp, cbsa]); db.flush()
        prompt = PromptTemplate(name="rewrite", version=1, purpose="REWRITE",
                                status="ACTIVE", system_prompt="system", user_prompt="user")
        db.add(prompt); db.flush()
        for site, suffix in ((cbp, "us"), (cbsa, "ca")):
            article = Article(source_site_id=site.id, normalized_url=f"https://{suffix}.test/1",
                              source_url=f"https://{suffix}.test/1", title="Original",
                              content="Original", content_hash="a" * 64, language="en")
            db.add(article); db.flush()
            db.add(ArticleImage(article_id=article.id, original_url=f"https://{suffix}.test/image.jpg",
                                position=0, download_status="SUCCESS"))
            translation = ArticleTranslation(article_id=article.id, source_content_hash="a" * 64,
                                             translated_content="译文", translation_status="SUCCESS",
                                             model_name="gpt-6-luna")
            db.add(translation); db.flush()
            db.add_all([
                ProcessedArticle(article_id=article.id, translation_id=translation.id,
                                 prompt_id=prompt.id, prompt_version=1, title=f"{suffix} 旧版",
                                 content="旧稿", model_name="gpt-6-luna", process_status="SUCCESS"),
                ProcessedArticle(article_id=article.id, translation_id=translation.id,
                                 prompt_id=prompt.id, prompt_version=1, title=f"{suffix} 最新版",
                                 content="新稿", model_name="gpt-6-luna", process_status="SUCCESS"),
                ProcessedArticle(article_id=article.id, translation_id=translation.id,
                                 prompt_id=prompt.id, prompt_version=1, title="模拟稿",
                                 content="模拟", model_name="mock-local", process_status="SUCCESS"),
            ])
        db.commit()
        cbp_id = cbp.id
        ca_article_id = db.query(Article.id).filter(Article.source_site_id == cbsa.id).scalar()

    try:
        response = client.get("/api/v1/rewritten-articles", params={"limit": 1})
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 2
        assert len(response.json()["articles"]) == 1
        assert client.get("/api/v1/rewritten-articles", params={"offset": 1, "limit": 1}).json()["count"] == 2
        us_page = client.get("/api/v1/rewritten-articles", params={"country": "us", "source_site_id": cbp_id}).json()
        assert us_page["count"] == 1
        item = us_page["articles"][0]
        assert item["title"] == "us 最新版"
        assert item["content"] == "新稿"
        assert item["country"] == "US" and item["site"] == "CBP"
        assert item["images"][0]["original_url"] == "https://us.test/image.jpg"
        assert "raw_response" not in item
        assert client.get("/api/articles").json()["articles"][0]["country"] == "CA"
        with sessions() as db:
            db.get(Article, ca_article_id).content_hash = "b" * 64
            db.commit()
        assert client.get("/api/v1/rewritten-articles").json()["count"] == 1
        assert client.get("/api/v1/rewritten-articles", params={"updated_since": datetime.now().isoformat()}).json()["count"] == 0
    finally:
        app.dependency_overrides.clear()


def test_remote_api_keys_are_scoped(monkeypatch):
    _, sessions = client_with_data()
    remote = TestClient(app, base_url="http://example.test", client=("203.0.113.10", 1234))
    monkeypatch.delenv("EXPORT_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    assert remote.get("/api/v1/rewritten-articles").status_code == 401
    monkeypatch.setenv("EXPORT_API_KEY", "export-test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-test-key")
    try:
        assert remote.get("/api/v1/rewritten-articles").status_code == 401
        assert remote.get("/api/v1/rewritten-articles", headers={"X-API-Key": "export-test-key"}).status_code == 200
        assert remote.get("/api/articles", headers={"X-API-Key": "export-test-key"}).status_code == 401
        assert remote.post("/api/v1/countries", json={"code": "US", "name": "US"},
                           headers={"X-API-Key": "export-test-key"}).status_code == 401
        assert remote.post("/api/v1/countries", json={"code": "US", "name": "US"},
                           headers={"X-API-Key": "admin-test-key"}).status_code == 201
        assert remote.get("/api/v1/rewritten-articles", headers={"X-API-Key": "admin-test-key"}).status_code == 200
        monkeypatch.setenv("ADMIN_API_KEY", "export-test-key")
        assert remote.get("/api/v1/rewritten-articles", headers={"X-API-Key": "export-test-key"}).status_code == 503
    finally:
        app.dependency_overrides.clear()

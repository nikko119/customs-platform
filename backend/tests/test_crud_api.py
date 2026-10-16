from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base, CrawlTask


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), engine


def test_country_site_article_prompt_crud():
    client, _ = make_client()
    country = client.post("/api/v1/countries", json={"code": "US", "name": "美国"})
    assert country.status_code == 201
    country_id = country.json()["id"]
    site = client.post("/api/v1/source-sites", json={
        "country_id": country_id, "site_code": "CBP", "name": "CBP",
        "base_url": "https://www.cbp.gov", "list_url": "https://www.cbp.gov/newsroom/media-releases/all"
    })
    assert site.status_code == 201
    site_id = site.json()["id"]
    article = client.post("/api/v1/articles", json={
        "source_site_id": site_id, "normalized_url": "https://example.test/news/1",
        "source_url": "https://example.test/news/1", "title": "Cargo seizure",
        "content": "Original content", "content_hash": "a" * 64
    })
    assert article.status_code == 201
    article_id = article.json()["id"]
    assert client.get("/api/v1/articles").json()[0]["title"] == "Cargo seizure"
    dashboard_articles = client.get("/api/articles", params={"q": "Cargo", "limit": 1, "offset": 0})
    assert dashboard_articles.status_code == 200
    assert dashboard_articles.json()["count"] == 1
    assert dashboard_articles.json()["articles"][0]["title"] == "Cargo seizure"
    assert client.get("/api/articles", params={"q": "missing"}).json()["count"] == 0
    assert client.patch(f"/api/v1/articles/{article_id}", json={"title": "Updated title"}).json()["title"] == "Updated title"
    prompt = client.post("/api/v1/prompts", json={"name": "news", "system_prompt": "system", "user_prompt": "user", "purpose": "REWRITE", "version": 1})
    assert prompt.status_code == 201
    translation_prompt = client.post("/api/v1/prompts", json={"name": "translate", "system_prompt": "translate", "user_prompt": "translate", "purpose": "TRANSLATE", "version": 1})
    assert translation_prompt.status_code == 201
    duplicate_prompt = client.post("/api/v1/prompts", json={"name": "news", "system_prompt": "changed", "user_prompt": "changed", "purpose": "REWRITE", "version": 1})
    assert duplicate_prompt.status_code == 409
    assert "名称和版本" in duplicate_prompt.json()["detail"]
    assert len(client.get("/api/v1/prompts").json()) == 2
    cleaned = client.post(f"/api/v1/articles/{article_id}/clean")
    assert cleaned.status_code == 200
    assert cleaned.json()["content"] == "Original content"
    assert cleaned.json()["cleaned_content"] == "Original content"
    simulated = client.post(f"/api/v1/articles/{article_id}/mock-process", json={"translation_prompt_id": translation_prompt.json()["id"], "rewrite_prompt_id": prompt.json()["id"]})
    assert simulated.status_code == 201
    assert simulated.json()["model_name"] == "mock-local"
    assert simulated.json()["prompt_version"] == 1
    assert "未调用真实模型" in simulated.json()["content"]
    assert simulated.json()["translation_id"] is not None
    translation = client.get(f"/api/v1/translations/{simulated.json()['translation_id']}")
    assert translation.status_code == 200
    assert translation.json()["source_language"] == "en"
    assert translation.json()["target_language"] == "zh-CN"
    assert "仍为英文清洗稿" in translation.json()["translated_content"]
    ai_tasks = client.get("/api/v1/ai-tasks").json()
    assert [task["task_type"] for task in ai_tasks] == ["REWRITE", "TRANSLATE"]
    assert ai_tasks[0]["status"] == "SUCCESS"
    assert ai_tasks[0]["processed_article_id"] == simulated.json()["id"]
    assert ai_tasks[0]["translation_id"] == simulated.json()["translation_id"]
    processed = client.post("/api/v1/processed-articles", json={
        "article_id": article_id, "prompt_id": prompt.json()["id"], "prompt_version": 1,
        "title": "改写标题", "content": "改写内容"
    })
    assert processed.status_code == 201
    task = client.post("/api/v1/crawl-tasks", json={"source_site_id": site_id, "max_pages": 1, "max_articles": 2})
    assert task.status_code == 201
    task_id = task.json()["id"]
    task_update = client.patch(f"/api/v1/crawl-tasks/{task_id}", json={
        "status": "SUCCESS", "success_count": 2, "new_count": 1, "updated_count": 1,
        "body_filtered_count": 3,
    })
    assert task_update.json()["new_count"] == 1
    assert task_update.json()["updated_count"] == 1
    assert task_update.json()["body_filtered_count"] == 3
    assert client.delete(f"/api/v1/articles/{article_id}").status_code == 204
    assert client.get(f"/api/v1/articles/{article_id}").status_code == 404
    app.dependency_overrides.clear()


def test_cleaner_normalizes_whitespace_and_adjacent_duplicate_paragraphs():
    from app.services.content_cleaner import clean_article_text

    result = clean_article_text("  First&nbsp; paragraph.  \n\nFirst paragraph.\n\nSecond\t paragraph.  ")
    assert result == "First paragraph.\n\nSecond paragraph."


def test_failed_crawl_before_first_page_does_not_break_task_list():
    client, engine = make_client()
    try:
        country = client.post("/api/v1/countries", json={"code": "US", "name": "United States"}).json()
        site = client.post("/api/v1/source-sites", json={
            "country_id": country["id"], "site_code": "CBP", "name": "CBP",
            "base_url": "https://www.cbp.gov", "list_url": "https://www.cbp.gov/newsroom/media-releases/all",
        }).json()
        task = client.post("/api/v1/crawl-tasks", json={"source_site_id": site["id"]}).json()
        with engine.begin() as connection:
            connection.execute(update(CrawlTask).where(CrawlTask.id == task["id"]).values(
                status="FAILED", max_pages=0, failed_count=1, error_message="浏览器启动失败",
            ))

        response = client.get("/api/v1/crawl-tasks")
        assert response.status_code == 200, response.text
        assert response.json()[0]["max_pages"] == 0
        assert response.json()[0]["status"] == "FAILED"
        assert client.get(f"/api/v1/crawl-tasks/{task['id']}").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_cleaner_removes_social_media_promotion_but_keeps_news_paragraphs():
    from app.services.content_cleaner import clean_article_text

    result = clean_article_text(
        "News fact with cargo details.\n\n"
        "Follow the Director of CBP on X @CBPNews and Instagram @cbp for breaking news, current events, human interest stories and photos."
    )
    assert result == "News fact with cargo details."
    discussion = clean_article_text("The report mentions Instagram as evidence.\n\nFollow CBP on social media.")
    assert discussion == "The report mentions Instagram as evidence."


def test_real_llm_process_persists_translation_and_rewrite_without_calling_network(monkeypatch):
    import app.api.crud as crud_api

    client, _ = make_client()
    monkeypatch.setattr(crud_api, "llm_configuration", lambda: ("http://local.test/v1", "test-key", "gpt-6-luna"))
    calls = []

    def fake_translate(system_prompt, user_prompt, content):
        calls.append(("translate", content))
        return "中文翻译正文", '{"translated_content":"中文翻译正文"}'

    def fake_rewrite(system_prompt, user_prompt, title, content):
        calls.append(("rewrite", title, content))
        return "中文标题", "中文改写正文", '{"title":"中文标题","content":"中文改写正文"}'

    monkeypatch.setattr(crud_api, "translate_article", fake_translate)
    monkeypatch.setattr(crud_api, "rewrite_article", fake_rewrite)

    country = client.post("/api/v1/countries", json={"code": "US", "name": "United States"}).json()
    site = client.post("/api/v1/source-sites", json={
        "country_id": country["id"], "site_code": "CBP", "name": "CBP",
        "base_url": "https://www.cbp.gov", "list_url": "https://www.cbp.gov/newsroom/media-releases/all"
    }).json()
    article = client.post("/api/v1/articles", json={
        "source_site_id": site["id"], "normalized_url": "https://example.test/llm",
        "source_url": "https://example.test/llm", "title": "Cargo update",
        "content": "English original", "content_hash": "b" * 64
    }).json()
    translate_prompt = client.post("/api/v1/prompts", json={
        "name": "translate-real-test", "system_prompt": "Translate faithfully", "user_prompt": "Translate",
        "purpose": "TRANSLATE", "version": 1
    }).json()
    rewrite_prompt = client.post("/api/v1/prompts", json={
        "name": "rewrite-real-test", "system_prompt": "Rewrite faithfully", "user_prompt": "Rewrite",
        "purpose": "REWRITE", "version": 1
    }).json()

    response = client.post(f"/api/v1/articles/{article['id']}/process", json={
        "translation_prompt_id": translate_prompt["id"], "rewrite_prompt_id": rewrite_prompt["id"]
    })

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["title"] == "中文标题"
    assert result["content"] == "中文改写正文"
    assert result["model_name"] == "gpt-6-luna"
    assert result["translation_id"] is not None
    translation = client.get(f"/api/v1/translations/{result['translation_id']}").json()
    assert translation["translated_content"] == "中文翻译正文"
    assert translation["translation_status"] == "SUCCESS"
    assert [call[0] for call in calls] == ["translate", "rewrite"]
    assert calls[0][1] == "English original"
    assert calls[1][2] == "中文翻译正文"
    assert client.get(f"/api/v1/articles/{article['id']}").json()["content"] == "English original"
    tasks = client.get("/api/v1/ai-tasks").json()
    assert {task["task_type"]: task["status"] for task in tasks} == {"TRANSLATE": "SUCCESS", "REWRITE": "SUCCESS"}
    app.dependency_overrides.clear()


def test_real_llm_process_requires_local_credentials(monkeypatch):
    import app.api.crud as crud_api

    client, _ = make_client()
    monkeypatch.setattr(crud_api, "llm_configuration", lambda: (_ for _ in ()).throw(
        RuntimeError("请先在 backend/.env 中配置：LLM_API_KEY")
    ))
    response = client.post("/api/v1/articles/1/process", json={
        "translation_prompt_id": 1, "rewrite_prompt_id": 2
    })
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]
    app.dependency_overrides.clear()

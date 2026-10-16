"""MySQL/SQLAlchemy 通用 CRUD API。

这些路由同样可使用 SQLite 运行测试；生产环境只需把 DATABASE_URL 指向 MySQL。
"""
from __future__ import annotations

from typing import Any, TypeVar
from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import (AiTask, Article, ArticleImage, ArticleTranslation, Country, CrawlTask,
                        ProcessedArticle, PromptTemplate, SourceSite)
from app.schemas.crud import (
    AiTaskCreate, AiTaskRead, AiTaskUpdate, ArticleCreate, ArticleRead,
    ArticleUpdate, CountryCreate, CountryRead, CountryUpdate, CrawlTaskCreate,
    CrawlTaskRead, CrawlTaskUpdate, ImageCreate, ImageRead, ImageUpdate, ProcessedCreate, ProcessedRead, ProcessedUpdate,
    ArticleTranslationRead, LlmProcessRequest, MockProcessRequest, PromptCreate, PromptRead, PromptUpdate, SourceSiteCreate, SourceSiteRead,
    SourceSiteUpdate,
)
from app.services.content_cleaner import clean_article_text
from app.services.mock_processor import build_mock_result, build_mock_translation
from app.llm.openai_compatible import llm_configuration, rewrite_article, translate_article

router = APIRouter(prefix="/api/v1", tags=["database"])
ModelT = TypeVar("ModelT")
LOGGER = logging.getLogger(__name__)


def _commit(db: Session, item: ModelT) -> ModelT:
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="数据重复或违反外键约束") from exc


def _get_or_404(db: Session, model: Any, item_id: int) -> Any:
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return item


def _update(db: Session, item: Any, changes: dict[str, Any]) -> Any:
    for key, value in changes.items():
        setattr(item, key, value)
    return _commit(db, item)


@router.post("/countries", response_model=CountryRead, status_code=status.HTTP_201_CREATED)
def create_country(payload: CountryCreate, db: Session = Depends(get_db)):
    return _commit(db, Country(**payload.model_dump()))


@router.get("/countries", response_model=list[CountryRead])
def list_countries(db: Session = Depends(get_db)):
    return db.scalars(select(Country).order_by(Country.id)).all()


@router.get("/countries/{item_id}", response_model=CountryRead)
def get_country(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Country, item_id)


@router.patch("/countries/{item_id}", response_model=CountryRead)
def update_country(item_id: int, payload: CountryUpdate, db: Session = Depends(get_db)):
    return _update(db, _get_or_404(db, Country, item_id), payload.model_dump(exclude_unset=True))


@router.delete("/countries/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_country(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, Country, item_id)
    try:
        db.delete(item); db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail="国家仍被官方站点引用，不能删除") from exc


@router.post("/source-sites", response_model=SourceSiteRead, status_code=201)
def create_source_site(payload: SourceSiteCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Country, payload.country_id)
    return _commit(db, SourceSite(**payload.model_dump()))


@router.get("/source-sites", response_model=list[SourceSiteRead])
def list_source_sites(country_id: int | None = None, db: Session = Depends(get_db)):
    query = select(SourceSite).order_by(SourceSite.id)
    if country_id is not None: query = query.where(SourceSite.country_id == country_id)
    return db.scalars(query).all()


@router.get("/source-sites/{item_id}", response_model=SourceSiteRead)
def get_source_site(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, SourceSite, item_id)


@router.patch("/source-sites/{item_id}", response_model=SourceSiteRead)
def update_source_site(item_id: int, payload: SourceSiteUpdate, db: Session = Depends(get_db)):
    item = _get_or_404(db, SourceSite, item_id)
    changes = payload.model_dump(exclude_unset=True)
    if "country_id" in changes: _get_or_404(db, Country, changes["country_id"])
    return _update(db, item, changes)


@router.delete("/source-sites/{item_id}", status_code=204)
def delete_source_site(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, SourceSite, item_id)
    try: db.delete(item); db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail="官方站点仍被新闻或任务引用") from exc


@router.post("/articles", response_model=ArticleRead, status_code=201)
def create_article(payload: ArticleCreate, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"images"})
    _get_or_404(db, SourceSite, data["source_site_id"])
    article = Article(**data)
    article.images = [ArticleImage(**image.model_dump()) for image in payload.images]
    return _commit(db, article)


@router.get("/articles", response_model=list[ArticleRead])
def list_articles_db(source_site_id: int | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = select(Article).options(selectinload(Article.images)).order_by(Article.id.desc()).offset(offset).limit(limit)
    if source_site_id is not None: query = query.where(Article.source_site_id == source_site_id)
    return db.scalars(query).all()


@router.get("/articles/{item_id}", response_model=ArticleRead)
def get_article_db(item_id: int, db: Session = Depends(get_db)):
    item = db.scalar(select(Article).options(selectinload(Article.images)).where(Article.id == item_id))
    if item is None: raise HTTPException(status_code=404, detail="记录不存在")
    return item


@router.patch("/articles/{item_id}", response_model=ArticleRead)
def update_article(item_id: int, payload: ArticleUpdate, db: Session = Depends(get_db)):
    item = _get_or_404(db, Article, item_id)
    changes = payload.model_dump(exclude_unset=True)
    if "source_site_id" in changes: _get_or_404(db, SourceSite, changes["source_site_id"])
    return _update(db, item, changes)


@router.delete("/articles/{item_id}", status_code=204)
def delete_article(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, Article, item_id); db.delete(item); db.commit()


@router.post("/articles/{item_id}/clean", response_model=ArticleRead)
def clean_article(item_id: int, db: Session = Depends(get_db)):
    """清洗正文并单独保存，原始 content 保持不变。"""
    item = _get_or_404(db, Article, item_id)
    item.cleaned_content = clean_article_text(item.content)
    db.commit()
    db.refresh(item)
    return item


@router.post("/articles/{item_id}/mock-process", response_model=ProcessedRead, status_code=201)
def mock_process_article(item_id: int, payload: MockProcessRequest, db: Session = Depends(get_db)):
    """模拟执行英文清洗稿 -> 中文翻译占位稿 -> 改写稿的两阶段流程。"""
    article = _get_or_404(db, Article, item_id)
    translation_prompt = _get_or_404(db, PromptTemplate, payload.translation_prompt_id)
    rewrite_prompt = _get_or_404(db, PromptTemplate, payload.rewrite_prompt_id)
    if translation_prompt.status != "ACTIVE" or rewrite_prompt.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="翻译和改写都必须选择启用中的提示词模板")
    if translation_prompt.purpose != "TRANSLATE" or rewrite_prompt.purpose != "REWRITE":
        raise HTTPException(status_code=400, detail="请分别选择翻译用途和改写用途的提示词模板")
    article.cleaned_content = clean_article_text(article.content)
    now = datetime.now()
    translation_task = AiTask(article_id=article.id, prompt_id=translation_prompt.id,
                              task_type="TRANSLATE", status="RUNNING",
                              model_name="mock-local", started_at=now)
    db.add(translation_task)
    db.flush()
    translation = ArticleTranslation(
        article_id=article.id, source_language=article.language or "en", target_language="zh-CN",
        source_content_hash=article.content_hash,
        translated_content=build_mock_translation(article.cleaned_content),
        translation_status="MOCK", prompt_id=translation_prompt.id, prompt_version=translation_prompt.version,
        model_name="mock-local",
    )
    db.add(translation)
    db.flush()
    translation_task.translation_id = translation.id
    translation_task.status = "SUCCESS"
    translation_task.finished_at = datetime.now()

    rewrite_task = AiTask(article_id=article.id, prompt_id=rewrite_prompt.id, translation_id=translation.id,
                          task_type="REWRITE", status="RUNNING", model_name="mock-local",
                          started_at=datetime.now())
    db.add(rewrite_task)
    db.flush()
    title, content, metadata = build_mock_result(article.title, translation.translated_content,
                                                 rewrite_prompt.name, rewrite_prompt.version)
    processed = ProcessedArticle(article_id=article.id, translation_id=translation.id,
                                 prompt_id=rewrite_prompt.id,
                                 prompt_version=rewrite_prompt.version, title=title, content=content,
                                 process_status="SUCCESS", model_name="mock-local",
                                 raw_response=metadata)
    db.add(processed)
    db.flush()
    rewrite_task.processed_article_id = processed.id
    rewrite_task.status = "SUCCESS"
    rewrite_task.finished_at = datetime.now()
    db.commit()
    db.refresh(processed)
    return processed


@router.post("/articles/{item_id}/process", response_model=ProcessedRead, status_code=201)
def process_article_with_llm(item_id: int, payload: LlmProcessRequest, db: Session = Depends(get_db)):
    """真实调用模型：先翻译，再改写；每一步结果和任务状态分别入库。"""
    try:
        _, _, model_name = llm_configuration()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    article = _get_or_404(db, Article, item_id)
    translation_prompt = _get_or_404(db, PromptTemplate, payload.translation_prompt_id)
    rewrite_prompt = _get_or_404(db, PromptTemplate, payload.rewrite_prompt_id)
    if translation_prompt.status != "ACTIVE" or rewrite_prompt.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="翻译和改写提示词都必须处于启用状态")
    if translation_prompt.purpose != "TRANSLATE" or rewrite_prompt.purpose != "REWRITE":
        raise HTTPException(status_code=400, detail="请分别选择翻译用途和改写用途的提示词")

    article.cleaned_content = clean_article_text(article.content)
    now = datetime.now()
    translate_task = AiTask(article_id=article.id, prompt_id=translation_prompt.id,
                            task_type="TRANSLATE", status="RUNNING", model_name=model_name,
                            started_at=now)
    rewrite_task = AiTask(article_id=article.id, prompt_id=rewrite_prompt.id,
                          task_type="REWRITE", status="PENDING", model_name=model_name)
    # SQLite 的测试环境由 before_flush 钩子分配 BIGINT ID，逐条 flush 才能避免新任务拿到相同 ID。
    db.add(translate_task)
    db.flush()
    db.add(rewrite_task)
    db.commit()
    db.refresh(translate_task)
    db.refresh(rewrite_task)

    try:
        translated_text, translation_raw = translate_article(
            translation_prompt.system_prompt, translation_prompt.user_prompt, article.cleaned_content
        )
        translation = ArticleTranslation(
            article_id=article.id, source_language=article.language or "en", target_language="zh-CN",
            source_content_hash=article.content_hash, translated_content=translated_text,
            translation_status="SUCCESS", prompt_id=translation_prompt.id,
            prompt_version=translation_prompt.version, model_name=model_name,
        )
        db.add(translation)
        db.flush()
        translate_task.translation_id = translation.id
        translate_task.status = "SUCCESS"
        translate_task.finished_at = datetime.now()
        translate_task.error_message = None
        db.commit()

        rewrite_task.status = "RUNNING"
        rewrite_task.started_at = datetime.now()
        db.commit()
        title, content, rewrite_raw = rewrite_article(
            rewrite_prompt.system_prompt, rewrite_prompt.user_prompt,
            article.title, translation.translated_content,
        )
        processed = ProcessedArticle(
            article_id=article.id, translation_id=translation.id,
            prompt_id=rewrite_prompt.id, prompt_version=rewrite_prompt.version,
            title=title, content=content, process_status="SUCCESS",
            model_name=model_name, raw_response=rewrite_raw,
        )
        db.add(processed)
        db.flush()
        rewrite_task.processed_article_id = processed.id
        rewrite_task.status = "SUCCESS"
        rewrite_task.finished_at = datetime.now()
        rewrite_task.error_message = None
        db.commit()
        db.refresh(processed)
        return processed
    except Exception as exc:
        db.rollback()
        LOGGER.exception("文章 %s 的模型处理失败", item_id)
        failed_task = db.get(AiTask, rewrite_task.id)
        if failed_task is not None and failed_task.status != "SUCCESS":
            failed_task.status = "FAILED"
            failed_task.error_message = f"模型调用或结果校验失败：{type(exc).__name__}"
            failed_task.finished_at = datetime.now()
        translate_task = db.get(AiTask, translate_task.id)
        if translate_task is not None and translate_task.status != "SUCCESS":
            translate_task.status = "FAILED"
            translate_task.error_message = f"模型调用或结果校验失败：{type(exc).__name__}"
            translate_task.finished_at = datetime.now()
        db.commit()
        raise HTTPException(status_code=502, detail="模型调用失败或返回内容格式不符合要求；请检查服务日志和中转站兼容情况") from exc


@router.post("/articles/{article_id}/images", response_model=ImageRead, status_code=201)
def create_image(article_id: int, payload: ImageCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Article, article_id)
    return _commit(db, ArticleImage(article_id=article_id, **payload.model_dump()))


@router.patch("/images/{item_id}", response_model=ImageRead)
def update_image(item_id: int, payload: ImageUpdate, db: Session = Depends(get_db)):
    return _update(db, _get_or_404(db, ArticleImage, item_id), payload.model_dump(exclude_unset=True))


@router.delete("/images/{item_id}", status_code=204)
def delete_image(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, ArticleImage, item_id); db.delete(item); db.commit()


@router.post("/prompts", response_model=PromptRead, status_code=201)
def create_prompt(payload: PromptCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(PromptTemplate).where(
        PromptTemplate.name == payload.name,
        PromptTemplate.version == payload.version,
    ))
    if existing is not None:
        raise HTTPException(status_code=409, detail="相同名称和版本的提示词模板已存在，请提高版本号或更改名称")
    return _commit(db, PromptTemplate(**payload.model_dump()))


@router.get("/prompts", response_model=list[PromptRead])
def list_prompts(db: Session = Depends(get_db)):
    return db.scalars(select(PromptTemplate).order_by(PromptTemplate.name, PromptTemplate.version.desc())).all()


@router.get("/prompts/{item_id}", response_model=PromptRead)
def get_prompt(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, PromptTemplate, item_id)


@router.patch("/prompts/{item_id}", response_model=PromptRead)
def update_prompt(item_id: int, payload: PromptUpdate, db: Session = Depends(get_db)):
    return _update(db, _get_or_404(db, PromptTemplate, item_id), payload.model_dump(exclude_unset=True))


@router.delete("/prompts/{item_id}", status_code=204)
def delete_prompt(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, PromptTemplate, item_id)
    try: db.delete(item); db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail="提示词已经被 AI 结果引用") from exc


@router.post("/processed-articles", response_model=ProcessedRead, status_code=201)
def create_processed_article(payload: ProcessedCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Article, payload.article_id); _get_or_404(db, PromptTemplate, payload.prompt_id)
    if payload.translation_id is not None: _get_or_404(db, ArticleTranslation, payload.translation_id)
    return _commit(db, ProcessedArticle(**payload.model_dump()))


@router.get("/translations", response_model=list[ArticleTranslationRead])
def list_translations(article_id: int | None = None, db: Session = Depends(get_db)):
    query = select(ArticleTranslation).order_by(ArticleTranslation.id.desc())
    if article_id is not None: query = query.where(ArticleTranslation.article_id == article_id)
    return db.scalars(query).all()


@router.get("/translations/{item_id}", response_model=ArticleTranslationRead)
def get_translation(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, ArticleTranslation, item_id)


@router.get("/processed-articles", response_model=list[ProcessedRead])
def list_processed_articles(article_id: int | None = None, db: Session = Depends(get_db)):
    query = select(ProcessedArticle).order_by(ProcessedArticle.id.desc())
    if article_id is not None: query = query.where(ProcessedArticle.article_id == article_id)
    return db.scalars(query).all()


@router.get("/processed-articles/{item_id}", response_model=ProcessedRead)
def get_processed_article(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, ProcessedArticle, item_id)


@router.patch("/processed-articles/{item_id}", response_model=ProcessedRead)
def update_processed_article(item_id: int, payload: ProcessedUpdate, db: Session = Depends(get_db)):
    item = _get_or_404(db, ProcessedArticle, item_id)
    changes = payload.model_dump(exclude_unset=True)
    if "prompt_id" in changes: _get_or_404(db, PromptTemplate, changes["prompt_id"])
    return _update(db, item, changes)


@router.delete("/processed-articles/{item_id}", status_code=204)
def delete_processed_article(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, ProcessedArticle, item_id); db.delete(item); db.commit()


@router.post("/crawl-tasks", response_model=CrawlTaskRead, status_code=201)
def create_crawl_task(payload: CrawlTaskCreate, db: Session = Depends(get_db)):
    _get_or_404(db, SourceSite, payload.source_site_id)
    return _commit(db, CrawlTask(**payload.model_dump()))


@router.get("/crawl-tasks", response_model=list[CrawlTaskRead])
def list_crawl_tasks(db: Session = Depends(get_db)):
    return db.scalars(select(CrawlTask).order_by(CrawlTask.id.desc())).all()


@router.get("/crawl-tasks/{item_id}", response_model=CrawlTaskRead)
def get_crawl_task(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, CrawlTask, item_id)


@router.patch("/crawl-tasks/{item_id}", response_model=CrawlTaskRead)
def update_crawl_task(item_id: int, payload: CrawlTaskUpdate, db: Session = Depends(get_db)):
    return _update(db, _get_or_404(db, CrawlTask, item_id), payload.model_dump(exclude_unset=True))


@router.post("/ai-tasks", response_model=AiTaskRead, status_code=201)
def create_ai_task(payload: AiTaskCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Article, payload.article_id); _get_or_404(db, PromptTemplate, payload.prompt_id)
    if payload.translation_id is not None: _get_or_404(db, ArticleTranslation, payload.translation_id)
    return _commit(db, AiTask(**payload.model_dump()))


@router.get("/ai-tasks", response_model=list[AiTaskRead])
def list_ai_tasks(db: Session = Depends(get_db)):
    return db.scalars(select(AiTask).order_by(AiTask.id.desc())).all()


@router.get("/ai-tasks/{item_id}", response_model=AiTaskRead)
def get_ai_task(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, AiTask, item_id)


@router.patch("/ai-tasks/{item_id}", response_model=AiTaskRead)
def update_ai_task(item_id: int, payload: AiTaskUpdate, db: Session = Depends(get_db)):
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("translation_id") is not None: _get_or_404(db, ArticleTranslation, changes["translation_id"])
    if changes.get("processed_article_id") is not None: _get_or_404(db, ProcessedArticle, changes["processed_article_id"])
    return _update(db, _get_or_404(db, AiTask, item_id), changes)


@router.delete("/ai-tasks/{item_id}", status_code=204)
def delete_ai_task(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, AiTask, item_id); db.delete(item); db.commit()

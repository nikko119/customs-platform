"""供外部系统按页拉取当前原文对应的最新真实改写稿。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Article, ArticleImage, ArticleTranslation, Country, ProcessedArticle, SourceSite

router = APIRouter(prefix="/api/v1", tags=["external export"])


class ExportImage(BaseModel):
    original_url: str
    alt: str | None
    position: int


class RewrittenArticle(BaseModel):
    article_id: int
    rewrite_id: int
    country: str
    site: str
    source_site_id: int
    source_url: str
    published_at: datetime | None
    title: str
    content: str
    images: list[ExportImage] = Field(default_factory=list)
    model_name: str | None
    prompt_version: int
    rewritten_at: datetime
    updated_at: datetime


class RewrittenPage(BaseModel):
    count: int
    limit: int
    offset: int
    articles: list[RewrittenArticle]


@router.get("/rewritten-articles", response_model=RewrittenPage)
def list_rewritten_articles(
    source_site_id: int | None = Query(default=None, ge=1),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    updated_since: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> RewrittenPage:
    """每篇只取最新一版；原文更新后，旧译文及其改写稿暂不对外输出。"""
    latest_id = (
        select(func.max(ProcessedArticle.id))
        .join(ArticleTranslation, ArticleTranslation.id == ProcessedArticle.translation_id)
        .where(
            ProcessedArticle.article_id == Article.id,
            ProcessedArticle.process_status == "SUCCESS",
            ProcessedArticle.model_name.is_not(None),
            ProcessedArticle.model_name != "mock-local",
            ArticleTranslation.translation_status == "SUCCESS",
            ArticleTranslation.source_content_hash == Article.content_hash,
        )
        .correlate(Article)
        .scalar_subquery()
    )
    conditions = [ProcessedArticle.id == latest_id]
    if source_site_id is not None:
        conditions.append(SourceSite.id == source_site_id)
    if country is not None:
        conditions.append(Country.code == country.upper())
    if updated_since is not None:
        conditions.append(ProcessedArticle.updated_at > updated_since)

    base = (
        select(Article, ProcessedArticle, SourceSite, Country)
        .join(ProcessedArticle, ProcessedArticle.article_id == Article.id)
        .join(SourceSite, SourceSite.id == Article.source_site_id)
        .join(Country, Country.id == SourceSite.country_id)
        .where(*conditions)
    )
    count = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(ProcessedArticle.updated_at.desc(), ProcessedArticle.id.desc())
        .limit(limit).offset(offset)
    ).all()
    article_ids = [article.id for article, _, _, _ in rows]
    images_by_article: dict[int, list[ExportImage]] = {article_id: [] for article_id in article_ids}
    if article_ids:
        images = db.scalars(
            select(ArticleImage).where(ArticleImage.article_id.in_(article_ids))
            .order_by(ArticleImage.article_id, ArticleImage.position, ArticleImage.id)
        ).all()
        for image in images:
            images_by_article[image.article_id].append(
                ExportImage(original_url=image.original_url, alt=image.alt, position=image.position)
            )
    return RewrittenPage(
        count=count, limit=limit, offset=offset,
        articles=[RewrittenArticle(
            article_id=article.id, rewrite_id=processed.id,
            country=nation.code, site=site.site_code, source_site_id=site.id,
            source_url=article.source_url, published_at=article.published_at,
            title=processed.title, content=processed.content,
            images=images_by_article[article.id], model_name=processed.model_name,
            prompt_version=processed.prompt_version,
            rewritten_at=processed.created_at, updated_at=processed.updated_at,
        ) for article, processed, site, nation in rows],
    )

"""第一期新闻采集与 AI 处理相关数据表。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Index, Integer,
                        JSON, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# MySQL 使用 BIGINT；SQLite 测试使用 INTEGER，确保自增主键行为一致。
IdentityBigInt = BigInteger().with_variant(Integer, "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class Country(TimestampMixin, Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True, comment="ISO 国家代码，例如 US")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    source_sites: Mapped[list[SourceSite]] = relationship(back_populates="country")


class SourceSite(TimestampMixin, Base):
    __tablename__ = "source_sites"
    __table_args__ = (UniqueConstraint("country_id", "site_code", name="uq_source_country_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False)
    site_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    list_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    crawl_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="抓取规则及关键词配置")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    country: Mapped[Country] = relationship(back_populates="source_sites")
    articles: Mapped[list[Article]] = relationship(back_populates="source_site")
    crawl_tasks: Mapped[list[CrawlTask]] = relationship(back_populates="source_site")


class Article(TimestampMixin, Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("source_site_id", "normalized_url", name="uq_article_site_url"),
        Index("ix_article_published_at", "published_at"),
        Index("ix_article_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(IdentityBigInt, primary_key=True, autoincrement=True)
    source_site_id: Mapped[int] = mapped_column(ForeignKey("source_sites.id", ondelete="RESTRICT"), nullable=False)
    # 700 字符可让 utf8mb4 下 (source_site_id, normalized_url) 联合唯一索引适配 MySQL 5.7。
    normalized_url: Mapped[str] = mapped_column(String(700), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default="en")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    cleaned_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="独立清洗结果，不覆盖原文")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_html_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    crawl_status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS", server_default="SUCCESS")
    first_crawled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    last_crawled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    source_site: Mapped[SourceSite] = relationship(back_populates="articles")
    images: Mapped[list[ArticleImage]] = relationship(back_populates="article", cascade="all, delete-orphan")
    translations: Mapped[list[ArticleTranslation]] = relationship(back_populates="article", cascade="all, delete-orphan")
    processed_versions: Mapped[list[ProcessedArticle]] = relationship(back_populates="article", cascade="all, delete-orphan")
    ai_tasks: Mapped[list[AiTask]] = relationship(back_populates="article", cascade="all, delete-orphan")


class ArticleImage(TimestampMixin, Base):
    __tablename__ = "news_images"
    __table_args__ = (Index("ix_news_image_article_position", "article_id", "position"),)

    id: Mapped[int] = mapped_column(IdentityBigInt, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False)
    original_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    alt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    download_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    article: Mapped[Article] = relationship(back_populates="images")


class PromptTemplate(TimestampMixin, Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="REWRITE", server_default="REWRITE")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    processed_articles: Mapped[list[ProcessedArticle]] = relationship(back_populates="prompt")
    ai_tasks: Mapped[list[AiTask]] = relationship(back_populates="prompt")


class ArticleTranslation(TimestampMixin, Base):
    __tablename__ = "news_translations"
    __table_args__ = (Index("ix_translation_article_created", "article_id", "created_at"),)

    id: Mapped[int] = mapped_column(IdentityBigInt, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False)
    source_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default="en")
    target_language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh-CN", server_default="zh-CN")
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    translated_content: Mapped[str] = mapped_column(Text, nullable=False)
    translation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="MOCK", server_default="MOCK")
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(191), nullable=True)
    article: Mapped[Article] = relationship(back_populates="translations")
    prompt: Mapped[PromptTemplate | None] = relationship()


class ProcessedArticle(TimestampMixin, Base):
    __tablename__ = "news_processed"
    __table_args__ = (Index("ix_processed_article_created", "article_id", "created_at"),)

    id: Mapped[int] = mapped_column(IdentityBigInt, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False)
    translation_id: Mapped[int | None] = mapped_column(ForeignKey("news_translations.id", ondelete="SET NULL"), nullable=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="RESTRICT"), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    process_status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS", server_default="SUCCESS")
    model_name: Mapped[str | None] = mapped_column(String(191), nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    article: Mapped[Article] = relationship(back_populates="processed_versions")
    translation: Mapped[ArticleTranslation | None] = relationship()
    prompt: Mapped[PromptTemplate] = relationship(back_populates="processed_articles")


class CrawlTask(TimestampMixin, Base):
    __tablename__ = "crawl_tasks"
    __table_args__ = (Index("ix_crawl_task_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(IdentityBigInt, primary_key=True, autoincrement=True)
    source_site_id: Mapped[int] = mapped_column(ForeignKey("source_sites.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    max_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_articles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawl_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="MANUAL", server_default="MANUAL")
    date_filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    body_filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_site: Mapped[SourceSite] = relationship(back_populates="crawl_tasks")


class AiTask(TimestampMixin, Base):
    __tablename__ = "llm_tasks"

    id: Mapped[int] = mapped_column(IdentityBigInt, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(20), nullable=False, default="REWRITE", server_default="REWRITE")
    translation_id: Mapped[int | None] = mapped_column(ForeignKey("news_translations.id", ondelete="SET NULL"), nullable=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="RESTRICT"), nullable=False)
    processed_article_id: Mapped[int | None] = mapped_column(ForeignKey("news_processed.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    model_name: Mapped[str | None] = mapped_column(String(191), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    article: Mapped[Article] = relationship(back_populates="ai_tasks")
    prompt: Mapped[PromptTemplate] = relationship(back_populates="ai_tasks")

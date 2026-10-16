"""数据库 CRUD 接口的请求和响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CountryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=2)
    name: str = Field(min_length=1, max_length=100)
    status: str = Field(default="ACTIVE", max_length=20)


class CountryUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=2)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: str | None = Field(default=None, max_length=20)


class CountryRead(CountryCreate, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class SourceSiteCreate(BaseModel):
    country_id: int
    site_code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=191)
    base_url: str = Field(min_length=1, max_length=500)
    list_url: str = Field(min_length=1, max_length=1000)
    crawl_config: dict[str, Any] | None = None
    status: str = Field(default="ACTIVE", max_length=20)


class SourceSiteUpdate(BaseModel):
    country_id: int | None = None
    site_code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=191)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    list_url: str | None = Field(default=None, min_length=1, max_length=1000)
    crawl_config: dict[str, Any] | None = None
    status: str | None = Field(default=None, max_length=20)


class SourceSiteRead(SourceSiteCreate, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class ImageCreate(BaseModel):
    original_url: str = Field(min_length=1, max_length=1000)
    local_path: str | None = Field(default=None, max_length=1000)
    alt: str | None = Field(default=None, max_length=500)
    position: int = Field(default=0, ge=0)
    download_status: str = Field(default="PENDING", max_length=20)


class ImageRead(ImageCreate, ORMModel):
    id: int
    article_id: int
    created_at: datetime
    updated_at: datetime


class ImageUpdate(BaseModel):
    original_url: str | None = Field(default=None, min_length=1, max_length=1000)
    local_path: str | None = Field(default=None, max_length=1000)
    alt: str | None = Field(default=None, max_length=500)
    position: int | None = Field(default=None, ge=0)
    download_status: str | None = Field(default=None, max_length=20)


class ArticleCreate(BaseModel):
    source_site_id: int
    normalized_url: str = Field(min_length=1, max_length=768)
    source_url: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=1000)
    author: str | None = Field(default=None, max_length=500)
    published_at: datetime | None = None
    language: str = Field(default="en", max_length=10)
    content: str
    content_hash: str = Field(min_length=64, max_length=64)
    raw_html_path: str | None = Field(default=None, max_length=1000)
    crawl_status: str = Field(default="SUCCESS", max_length=20)
    images: list[ImageCreate] = Field(default_factory=list)


class ArticleUpdate(BaseModel):
    source_site_id: int | None = None
    source_url: str | None = Field(default=None, min_length=1, max_length=1000)
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    author: str | None = Field(default=None, max_length=500)
    published_at: datetime | None = None
    language: str | None = Field(default=None, max_length=10)
    content: str | None = None
    cleaned_content: str | None = None
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    raw_html_path: str | None = Field(default=None, max_length=1000)
    crawl_status: str | None = Field(default=None, max_length=20)


class ArticleRead(ORMModel):
    id: int
    source_site_id: int
    normalized_url: str
    source_url: str
    title: str
    author: str | None
    published_at: datetime | None
    language: str
    content: str
    cleaned_content: str | None
    content_hash: str
    raw_html_path: str | None
    crawl_status: str
    first_crawled_at: datetime
    last_crawled_at: datetime
    created_at: datetime
    updated_at: datetime
    images: list[ImageRead] = Field(default_factory=list)


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    system_prompt: str
    user_prompt: str
    purpose: str = Field(default="REWRITE", max_length=20)
    version: int = Field(ge=1)
    status: str = Field(default="ACTIVE", max_length=20)


class PromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=191)
    system_prompt: str | None = None
    user_prompt: str | None = None
    purpose: str | None = Field(default=None, max_length=20)
    version: int | None = Field(default=None, ge=1)
    status: str | None = Field(default=None, max_length=20)


class PromptRead(PromptCreate, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class ProcessedCreate(BaseModel):
    article_id: int
    translation_id: int | None = None
    prompt_id: int
    prompt_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=1000)
    content: str
    process_status: str = Field(default="SUCCESS", max_length=20)
    model_name: str | None = Field(default=None, max_length=191)
    raw_response: str | None = None


class ProcessedUpdate(BaseModel):
    prompt_id: int | None = None
    prompt_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    content: str | None = None
    process_status: str | None = Field(default=None, max_length=20)
    model_name: str | None = Field(default=None, max_length=191)
    raw_response: str | None = None


class ProcessedRead(ProcessedCreate, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class MockProcessRequest(BaseModel):
    translation_prompt_id: int
    rewrite_prompt_id: int


class LlmProcessRequest(BaseModel):
    translation_prompt_id: int
    rewrite_prompt_id: int


class ArticleTranslationRead(ORMModel):
    id: int
    article_id: int
    source_language: str
    target_language: str
    source_content_hash: str
    translated_content: str
    translation_status: str
    prompt_id: int | None
    prompt_version: int | None
    model_name: str | None
    created_at: datetime
    updated_at: datetime


class CrawlTaskCreate(BaseModel):
    source_site_id: int
    status: str = Field(default="PENDING", max_length=20)
    max_pages: int | None = Field(default=None, ge=1)
    max_articles: int | None = Field(default=None, ge=1)
    crawl_mode: str = Field(default="MANUAL", max_length=30)


class CrawlTaskUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    discovered_count: int | None = Field(default=None, ge=0)
    filtered_count: int | None = Field(default=None, ge=0)
    body_filtered_count: int | None = Field(default=None, ge=0)
    date_filtered_count: int | None = Field(default=None, ge=0)
    success_count: int | None = Field(default=None, ge=0)
    new_count: int | None = Field(default=None, ge=0)
    updated_count: int | None = Field(default=None, ge=0)
    unchanged_count: int | None = Field(default=None, ge=0)
    failed_count: int | None = Field(default=None, ge=0)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CrawlTaskRead(CrawlTaskCreate, ORMModel):
    id: int
    # 浏览器启动前失败时，实际访问页数为 0；创建任务时的页数限制仍从 1 开始。
    max_pages: int | None = Field(default=None, ge=0)
    discovered_count: int
    filtered_count: int
    body_filtered_count: int
    date_filtered_count: int
    success_count: int
    new_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AiTaskCreate(BaseModel):
    article_id: int
    prompt_id: int
    task_type: str = Field(default="REWRITE", max_length=20)
    translation_id: int | None = None
    processed_article_id: int | None = None
    status: str = Field(default="PENDING", max_length=20)
    model_name: str | None = Field(default=None, max_length=191)


class AiTaskUpdate(BaseModel):
    processed_article_id: int | None = None
    task_type: str | None = Field(default=None, max_length=20)
    translation_id: int | None = None
    status: str | None = Field(default=None, max_length=20)
    model_name: str | None = Field(default=None, max_length=191)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AiTaskRead(AiTaskCreate, ORMModel):
    id: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

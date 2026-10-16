"""将 CBP 抓取结果持久化到数据库。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Article, ArticleImage, Country, SourceSite
from crawlers.site import ArticleLike


def parse_published_at(value: str | None) -> datetime | None:
    """把 CBP 的日期文本转成数据库 DateTime；无法识别时保留为空。"""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%a, %m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def ensure_cbp_source(db: Session) -> SourceSite:
    """确保 US/CBP 基础数据存在，返回后续文章使用的站点。"""
    country = db.scalar(select(Country).where(Country.code == "US"))
    if country is None:
        country = Country(code="US", name="United States", status="ACTIVE")
        db.add(country)
        db.flush()
    site = db.scalar(select(SourceSite).where(SourceSite.country_id == country.id, SourceSite.site_code == "CBP"))
    if site is None:
        site = SourceSite(country_id=country.id, site_code="CBP", name="U.S. Customs and Border Protection",
                          base_url="https://www.cbp.gov", list_url="https://www.cbp.gov/newsroom/media-releases/all",
                          status="ACTIVE")
        db.add(site)
        db.flush()
    return site


def get_source_site(db: Session, source_site_id: int) -> SourceSite:
    """按站点 ID 读取持久化目标，避免新站点写入 CBP 的记录。"""
    site = db.get(SourceSite, source_site_id)
    if site is None:
        raise ValueError(f"站点不存在: {source_site_id}")
    return site


def upsert_crawled_article(db: Session, site: SourceSite, crawled: ArticleLike, raw_html_path: str | None = None) -> str:
    """按站点和规范化 URL 新增或更新新闻，返回 NEW、UPDATED 或 UNCHANGED。"""
    article = db.scalar(select(Article).where(Article.source_site_id == site.id, Article.normalized_url == crawled.source_url).options(selectinload(Article.images)))
    now = datetime.now()
    if article is None:
        article = Article(source_site_id=site.id, normalized_url=crawled.source_url, source_url=crawled.source_url,
                          title=crawled.title, author=crawled.author, published_at=parse_published_at(crawled.published_at),
                          language=crawled.language, content=crawled.content, content_hash=crawled.content_hash,
                          raw_html_path=raw_html_path, crawl_status=crawled.crawl_status,
                          first_crawled_at=now, last_crawled_at=now)
        article.images = [ArticleImage(original_url=image.original_url, local_path=image.local_path or None,
                                       alt=image.alt or None, position=image.position,
                                       download_status="SUCCESS" if image.local_path else "FAILED")
                         for image in crawled.images]
        db.add(article)
        return "NEW"
    article.last_crawled_at = now
    article.crawl_status = crawled.crawl_status
    if article.content_hash == crawled.content_hash:
        return "UNCHANGED"
    article.title = crawled.title
    article.author = crawled.author
    article.published_at = parse_published_at(crawled.published_at)
    article.content = crawled.content
    article.content_hash = crawled.content_hash
    article.raw_html_path = raw_html_path
    article.images.clear()
    article.images.extend(ArticleImage(original_url=image.original_url, local_path=image.local_path or None,
                                       alt=image.alt or None, position=image.position,
                                       download_status="SUCCESS" if image.local_path else "FAILED")
                          for image in crawled.images)
    return "UPDATED"


def import_json_articles(db: Session, output_dir: Path) -> int:
    """把旧版 JSON 结果导入数据库；已有相同 URL 时不会覆盖数据库内容。"""
    article_dir = output_dir / "articles"
    if not article_dir.is_dir():
        return 0
    site = ensure_cbp_source(db)
    imported = 0
    for path in article_dir.glob("*.json"):
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            existing = db.scalar(select(Article).where(Article.source_site_id == site.id, Article.normalized_url == data["source_url"]))
            if existing is not None:
                continue
            article = Article(source_site_id=site.id, normalized_url=data["source_url"], source_url=data["source_url"],
                              title=data.get("title", ""), author=data.get("author"),
                              published_at=parse_published_at(data.get("published_at")), language=data.get("language", "en"),
                              content=data.get("content", ""), content_hash=data.get("content_hash", ""),
                              raw_html_path=None, crawl_status=data.get("crawl_status", "SUCCESS"))
            article.images = [ArticleImage(original_url=image.get("original_url", ""), local_path=image.get("local_path"),
                                           alt=image.get("alt"), position=image.get("position", 0),
                                           download_status="SUCCESS" if image.get("local_path") else "PENDING")
                             for image in data.get("images", [])]
            db.add(article)
            imported += 1
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    if imported:
        db.commit()
    return imported


def import_all_legacy_json(db: Session, data_root: Path) -> int:
    """导入 data 下各次抓取遗留的 JSON，避免更换输出目录后旧新闻不显示。"""
    directories = [data_root]
    directories.extend(path for path in data_root.iterdir() if path.is_dir())
    total = 0
    for directory in directories:
        total += import_json_articles(db, directory)
    return total

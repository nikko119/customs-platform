"""可复用抓取流程使用的站点适配器定义。每个网站只需提供自己的页面规则。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Protocol


class ArticleLike(Protocol):
    source_url: str
    title: str
    content: str
    content_hash: str
    images: list


@dataclass(frozen=True)
class SiteAdapter:
    """站点差异配置；公共抓取引擎不需要知道各站点的 HTML 结构。"""

    country: str
    site: str
    list_url: str
    keywords: tuple[str, ...]
    parse_listing: Callable[[str, str], list[dict]]
    parse_article: Callable[[str, str], ArticleLike]
    normalize_url: Callable[[str, str], str]
    page_url: Callable[[int], str]
    matches_body: Callable[[str, Iterable[str]], bool]


@dataclass
class CrawlOptions:
    output_dir: Path
    max_pages: int | None = 1
    max_articles: int | None = 10
    published_after: datetime | None = None
    crawl_mode: str = "MANUAL"
    interval: float = 1.5
    include_content: bool = False
    headless: bool = True
    slow_mo: float = 0


@dataclass
class CrawlCallbacks:
    """把数据库写入交由调用方，公共引擎本身不绑定具体数据库业务。"""

    persist_article: Callable[[ArticleLike, str], str]

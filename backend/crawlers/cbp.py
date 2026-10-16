"""CBP 页面解析、筛选和 JSON 历史记录。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

LOGGER = logging.getLogger(__name__)
DEFAULT_URL = "https://www.cbp.gov/newsroom/media-releases/all"
DEFAULT_KEYWORDS = ("seize", "seized", "seizure", "intercept", "customs", "tariff", "package", "parcel", "shipping", "smuggling", "counterfeit", "import", "cargo", "duty", "courier")


def parse_published_datetime(value: str | None) -> datetime | None:
    """把列表页日期转换成无时区 datetime，供近 N 天筛选使用。"""
    if not value:
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for fmt in ("%a, %m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _listing_published_at(time_node: Tag | None) -> str | None:
    """CBP 当前列表的 datetime 属性可能陈旧，优先解析用户实际看到的日期文字。"""
    if time_node is None:
        return None

    visible_date: str | None = None
    month = time_node.select_one(".usa-collection__calendar-date-month")
    day = time_node.select_one(".usa-collection__calendar-date-day")
    if month and day:
        # 当前页面把“Oct 14”和“2026”分别放在 month/day 命名的 span 中。
        visible_date = f"{_text(month)} { _text(day) }"
    else:
        visible_date = _text(time_node)

    parsed = parse_published_datetime(visible_date)
    if parsed is not None:
        return parsed.date().isoformat()

    # 兼容离线旧样本以及没有可读日期文字的页面。
    machine_date = time_node.get("datetime")
    parsed = parse_published_datetime(machine_date)
    return parsed.date().isoformat() if parsed is not None else machine_date or None


@dataclass
class ArticleImage:
    original_url: str
    local_path: str = ""
    alt: str = ""
    position: int = 0


@dataclass
class Article:
    country: str
    site: str
    source_url: str
    title: str
    author: str | None
    published_at: str | None
    language: str
    content: str
    content_hash: str
    images: list[ArticleImage]
    crawl_status: str
    crawled_at: str


def normalize_url(url: str, base_url: str = DEFAULT_URL) -> str:
    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def matches_keywords(text: str, keywords: Iterable[str]) -> bool:
    """正文二次筛选：正文里命中任意一个配置关键词即保留。"""
    terms = tuple(term.strip().lower() for term in keywords if term.strip())
    return not terms or any(term in text.lower() for term in terms)


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def _is_promotional_paragraph(text: str) -> bool:
    """过滤正文末尾的账号关注和社交媒体推广信息。"""
    lowered = text.lower()
    return (
        lowered.startswith("follow the director")
        or lowered.startswith("follow cbp")
        or lowered.startswith("follow us")
        or lowered.startswith("connect with cbp")
        or lowered.startswith("breaking news, current events")
    )


def parse_article_html(html: str, source_url: str, *, crawled_at: str | None = None) -> Article:
    """仅解析 CBP 新闻主体字段，避免收录搜索框、社交链接和页脚。"""
    soup = BeautifulSoup(html, "lxml")
    # 以下字段选择器已在 CBP 实际详情页 HTML 中确认。
    title = _text(soup.select_one("h1#page-title")) or _text(soup.select_one("h1"))
    article_node = soup.select_one("main article")
    if not article_node or not title:
        raise ValueError("未找到 CBP 新闻标题或 main/article，页面结构可能已变化")

    date_node = article_node.select_one(".field--name-field-date-release .field__item")
    published = _text(date_node) or None
    author_node = article_node.select_one(".field--name-field-author .field__item, [rel=author]")
    author = _text(author_node) or None

    # CBP 页面会重复使用 field--name-body 展示社交信息和页脚；正文块包含新闻段落。
    candidates = article_node.select(".field--name-body")
    body = next((node for node in candidates if node.select_one("p")), None)
    if body is None:
        raise ValueError("未找到包含段落的新闻正文，页面结构可能已变化")
    for selector in ("script", "style", "noscript", "nav", "footer", ".share", ".social-links"):
        for node in body.select(selector):
            node.decompose()
    article_paragraphs: list[str] = []
    for paragraph in body.select("p"):
        text = re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True))
        if not text:
            continue
        if _is_promotional_paragraph(text):
            break
        article_paragraphs.append(text)
    content = "\n\n".join(article_paragraphs)
    if not content:
        raise ValueError("CBP 新闻正文为空")

    images: list[ArticleImage] = []
    for position, img in enumerate(body.select("img")):
        src = img.get("src") or img.get("data-src")
        if src:
            images.append(ArticleImage(normalize_url(src, source_url), "", img.get("alt", ""), position))

    return Article("US", "CBP", normalize_url(source_url), title, author, published, "en", content,
                   content_hash(content), images, "SUCCESS", crawled_at or datetime.now(timezone.utc).isoformat())


def parse_listing_html(html: str, base_url: str = DEFAULT_URL) -> list[dict[str, str | None]]:
    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, str | None]] = []
    seen: set[str] = set()
    # .usa-collection__heading a 与 .usa-collection__calendar-date 来自已保存的真实列表 HTML。
    for heading in soup.select(".usa-collection__heading a[href]"):
        href = normalize_url(heading["href"], base_url)
        if href in seen:
            continue
        seen.add(href)
        entry = heading.find_parent(class_="usa-collection__item")
        time = entry.select_one(".usa-collection__calendar-date time") if entry else None
        results.append({"url": href, "title": _text(heading), "published_at": _listing_published_at(time)})
    return results


def parse_pagination_html(html: str, current_url: str = DEFAULT_URL) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    pager = soup.select_one("nav.usa-pagination")
    if not pager:
        return []
    current = pager.select_one("a[aria-current=page]")
    current_href = _page_url(current.get("href", ""), current_url) if current else None
    urls = []
    for link in pager.select("a[href]"):
        candidate = _page_url(link["href"], current_url)
        if candidate != current_href and candidate not in urls:
            urls.append(candidate)
    return urls


def _page_url(url: str, base_url: str = DEFAULT_URL) -> str:
    """列表分页参数有意义，需要在规范化时保留查询字符串。"""
    from urllib.parse import urljoin
    parsed = urlparse(urljoin(base_url, url))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", parsed.query, ""))


def filter_listing(items: Iterable[dict], keywords: Iterable[str] = DEFAULT_KEYWORDS, limit: int | None = None,
                   include_content: bool = False) -> tuple[list[dict], int]:
    terms = tuple(k.strip().lower() for k in keywords if k.strip())
    matches: list[dict] = []
    filtered = 0
    for item in items:
        haystack = (str(item.get("title", "")) + (" " + str(item.get("content", "")) if include_content else "")).lower()
        if terms and not any(term in haystack for term in terms):
            filtered += 1
            continue
        matches.append(item)
    return (matches[:limit] if limit is not None else matches), filtered


def load_history(path: str | Path) -> dict[str, dict[str, str]]:
    history_path = Path(path)
    if not history_path.exists():
        return {}
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("读取历史索引失败: %s", history_path)
        return {}


def save_history(path: str | Path, history: dict[str, dict[str, str]]) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def save_article_json(article: Article, path: str | Path) -> None:
    article_path = Path(path)
    article_path.parent.mkdir(parents=True, exist_ok=True)
    article_path.write_text(json.dumps(asdict(article), ensure_ascii=False, indent=2), encoding="utf-8")

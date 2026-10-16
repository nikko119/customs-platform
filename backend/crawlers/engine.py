"""各国家和站点共用的 Playwright 抓取流程。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from crawlers.site import CrawlCallbacks, CrawlOptions, SiteAdapter

LOGGER = logging.getLogger("crawler.engine")


def _parse_listing_datetime(value: object) -> datetime | None:
    """解析列表页常见 ISO/英文日期；解析失败时返回 None，避免误删新闻。"""
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%a, %m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def filter_listing_date(items: list[dict], published_after: datetime) -> tuple[list[dict], int, bool]:
    """保留窗口内及日期未知的新闻，并判断当前页是否全都早于窗口。"""
    kept: list[dict] = []
    old_count = 0
    dated_count = 0
    for item in items:
        published = _parse_listing_datetime(item.get("published_at"))
        if published is None:
            kept.append(item)
        elif published >= published_after:
            kept.append(item)
            dated_count += 1
        else:
            old_count += 1
            dated_count += 1
    return kept, old_count, dated_count > 0 and old_count == dated_count


def _chromium_executable() -> str | None:
    configured = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    browser_roots = [Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH", ""))] if os.getenv("PLAYWRIGHT_BROWSERS_PATH") else []
    browser_roots.append(Path(__file__).resolve().parents[1] / "data" / "browsers")
    for root in browser_roots:
        for pattern in ("chromium-*/chrome-win64/chrome.exe", "chromium-*/chrome-linux/chrome",
                        "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
            candidates = sorted(root.glob(pattern), reverse=True)
            if candidates:
                return str(candidates[0])
    return None


def filter_titles(items: list[dict], keywords: Iterable[str], limit: int | None,
                  include_content: bool = False) -> tuple[list[dict], int]:
    """通用标题关键词筛选；列表摘要筛选仍由可选参数控制。"""
    terms = tuple(term.strip().casefold() for term in keywords if term.strip())
    matched: list[dict] = []
    filtered = 0
    for item in items:
        text = str(item.get("title", ""))
        if include_content:
            text += " " + str(item.get("content", ""))
        if terms and not any(term in text.casefold() for term in terms):
            filtered += 1
            continue
        matched.append(item)
    return matched[:limit], filtered


async def _visit(page, url: str, folder: Path, name: str) -> dict:
    """访问页面并保留原始 HTML 和截图；403/429 按访问失败处理。"""
    folder.mkdir(parents=True, exist_ok=True)
    result = {"url": url, "status": None, "title": None, "html": None, "error": None}
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        result["status"] = response.status if response else None
        result["title"] = await page.title()
        html_path = folder / f"{name}.html"
        html_path.write_text(await page.content(), encoding="utf-8")
        result["html"] = str(html_path)
        await page.screenshot(path=str(folder / f"{name}.png"), full_page=True)
        if result["status"] in (403, 429):
            result["error"] = f"HTTP {result['status']}：网站拒绝访问或请求过于频繁"
    except PlaywrightTimeoutError as exc:
        result["error"] = f"页面超时: {exc}"
    except Exception as exc:
        result["error"] = f"访问失败: {exc}"
        LOGGER.exception("访问页面失败: %s", url)
    if result["error"]:
        LOGGER.error("%s (%s)", result["error"], url)
    else:
        LOGGER.info("页面访问完成 status=%s title=%s url=%s", result["status"], result["title"], url)
    return result


async def _download_images(request, article, image_dir: Path) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    for image in article.images:
        try:
            response = await request.get(image.original_url, timeout=30_000)
            if not response.ok:
                LOGGER.warning("图片下载失败 HTTP %s: %s", response.status, image.original_url)
                continue
            suffix = Path(urlparse(image.original_url).path).suffix.lower()
            suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,5}", suffix) else ".bin"
            target = image_dir / f"{article.content_hash[:16]}_{image.position}{suffix}"
            target.write_bytes(await response.body())
            image.local_path = str(target)
        except Exception:
            LOGGER.exception("图片下载异常: %s", image.original_url)


def _save_json(article, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(article) if is_dataclass(article) else article.__dict__
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_history(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("历史索引读取失败: %s", path)
        return {}


def _save_history(path: Path, history: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_site_crawl(adapter: SiteAdapter, options: CrawlOptions,
                         callbacks: CrawlCallbacks) -> dict:
    """运行通用抓取流程，站点适配器决定 URL 和 HTML 解析，回调决定如何持久化。"""
    root = options.output_dir
    raw_listing, raw_articles = root / "raw" / "listing", root / "raw" / "articles"
    article_dir, image_dir = root / "articles", root / "images"
    history_path = root / "history.json"
    history = _load_history(history_path)
    discovered: list[dict] = []
    errors: list[str] = []

    LOGGER.info("开始抓取 site=%s mode=%s page_limit=%s published_after=%s max_articles=%s",
                adapter.site, options.crawl_mode, options.max_pages,
                options.published_after.isoformat() if options.published_after else None,
                options.max_articles)

    async with async_playwright() as playwright:
        launch_options = {"headless": options.headless, "slow_mo": options.slow_mo}
        executable = _chromium_executable()
        if executable:
            launch_options["executable_path"] = executable
        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context()
        page = await context.new_page()
        page_no = 0
        pages_visited = 0
        date_filtered = 0
        while (options.max_pages is None and page_no < 1000) or (
            options.max_pages is not None and page_no < options.max_pages
        ):
            list_url = adapter.page_url(page_no)
            result = await _visit(page, list_url, raw_listing, f"page_{page_no}")
            if result["error"] or not result["html"]:
                errors.append(result["error"] or f"列表无响应: {list_url}")
                page_no += 1
                pages_visited += 1
                break
            try:
                html = Path(result["html"]).read_text(encoding="utf-8")
                page_items = adapter.parse_listing(html, list_url)
                if not page_items:
                    if page_no == 0:
                        message = f"第一页没有解析到新闻条目，页面结构可能变化: {list_url}"
                        errors.append(message)
                        LOGGER.error(message)
                    pages_visited += 1
                    break
                if options.published_after is not None:
                    kept, old_items, page_is_old = filter_listing_date(page_items, options.published_after)
                    date_filtered += old_items
                    discovered.extend(kept)
                    # CBP 列表按时间倒序。遇到整页都有日期且全部早于窗口时即可停止翻页。
                    if page_is_old:
                        pages_visited += 1
                        break
                else:
                    discovered.extend(page_items)
            except Exception as exc:
                errors.append(f"列表解析失败 {list_url}: {exc}")
                LOGGER.exception("列表解析失败: %s", list_url)
            pages_visited += 1
            page_no += 1
            if options.max_pages is not None and page_no >= options.max_pages:
                break
            if options.max_pages is None or page_no < options.max_pages:
                await asyncio.sleep(options.interval)

        # 跨页规范化 URL 去重，保留官网第一次出现的顺序。
        unique: list[dict] = []
        seen_urls: set[str] = set()
        for item in discovered:
            normalized = adapter.normalize_url(str(item.get("url", "")), adapter.list_url)
            if not normalized or normalized in seen_urls:
                continue
            item["url"] = normalized
            seen_urls.add(normalized)
            unique.append(item)
        selected, filtered_count = filter_titles(unique, adapter.keywords, options.max_articles,
                                                 options.include_content)
        success = new_count = updated = unchanged = body_filtered = 0
        for index, item in enumerate(selected):
            result = await _visit(page, item["url"], raw_articles, f"article_{index}")
            if result["error"] or not result["html"]:
                errors.append(result["error"] or f"详情无响应: {item['url']}")
                continue
            try:
                raw_html_path = str(Path(result["html"]).resolve())
                article = adapter.parse_article(Path(result["html"]).read_text(encoding="utf-8"), item["url"])
                if not adapter.matches_body(article.content, adapter.keywords):
                    body_filtered += 1
                    LOGGER.info("正文关键词未命中，筛除文章: %s", article.title)
                else:
                    await _download_images(context.request, article, image_dir)
                    _save_json(article, article_dir / f"{article.content_hash[:16]}.json")
                    outcome = callbacks.persist_article(article, raw_html_path)
                    if outcome == "NEW":
                        new_count += 1
                    elif outcome == "UPDATED":
                        updated += 1
                    else:
                        unchanged += 1
                    success += 1
                    history[article.source_url] = {
                        "content_hash": article.content_hash,
                        "article_file": str(article_dir / f"{article.content_hash[:16]}.json"),
                    }
            except Exception as exc:
                errors.append(f"文章处理失败 {item['url']}: {exc}")
                LOGGER.exception("文章处理失败: %s", item["url"])
            await asyncio.sleep(options.interval)
        await browser.close()

    _save_history(history_path, history)
    summary = {"discovered": len(discovered), "selected": len(selected), "filtered": filtered_count,
               "date_filtered": date_filtered, "pages_visited": pages_visited,
               "crawl_mode": options.crawl_mode,
               "body_filtered": body_filtered, "success": success, "new": new_count,
               "updated": updated, "unchanged": unchanged, "errors": errors}
    LOGGER.info("%s 抓取完成: %s", adapter.site, summary)
    return summary

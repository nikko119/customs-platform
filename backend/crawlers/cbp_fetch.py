"""CBP Playwright 抓取入口：自动抓取最近一段时间的新闻。"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
from app.core.database import SessionLocal
from app.services.article_persistence import ensure_cbp_source
from .cbp import DEFAULT_KEYWORDS, DEFAULT_URL, Article, matches_keywords, parse_article_html, parse_listing_html
from .runner import run_managed_site_crawl
from .site import SiteAdapter

LOGGER = logging.getLogger("cbp")


def configure_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", force=True)


def _page_url(url: str, base_url: str) -> str:
    """保留分页查询参数，避免页码被 URL 规范化逻辑删掉。"""
    from urllib.parse import urljoin, urlunparse
    parsed = urlparse(urljoin(base_url, url))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", parsed.query, ""))


async def fetch_page(page, url: str, output_dir: str | Path, *, name: str = "cbp_page") -> dict:
    """访问页面并保存 HTML/截图，明确记录 403、429 和超时。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {"url": url, "status": None, "title": None, "html": None, "screenshot": None, "error": None}
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        result["status"] = response.status if response else None
        result["title"] = await page.title()
        result["html"] = str(out / f"{name}.html")
        result["screenshot"] = str(out / f"{name}.png")
        Path(result["html"]).write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=result["screenshot"], full_page=True)
        if result["status"] in (403, 429):
            result["error"] = f"HTTP {result['status']}，网站拒绝访问或请求过于频繁"
            LOGGER.error("%s: %s", result["error"], url)
    except PlaywrightTimeoutError as exc:
        result["error"] = f"页面超时: {exc}"
        LOGGER.error("%s (%s)", result["error"], url)
    except Exception as exc:
        result["error"] = f"访问失败: {exc}"
        LOGGER.exception("%s (%s)", result["error"], url)
    return result


async def download_images(request, article: Article, image_dir: Path) -> None:
    """下载正文图片，失败时保留原始 URL 并记录日志。"""
    image_dir.mkdir(parents=True, exist_ok=True)
    for image in article.images:
        try:
            response = await request.get(image.original_url, timeout=30_000)
            if not response.ok:
                LOGGER.warning("图片下载失败 HTTP %s: %s", response.status, image.original_url)
                continue
            from urllib.parse import urlparse
            from pathlib import PurePosixPath
            suffix = PurePosixPath(urlparse(image.original_url).path).suffix.lower()
            suffix = suffix if suffix and len(suffix) <= 6 else ".bin"
            target = image_dir / f"{article.content_hash[:16]}_{image.position}{suffix}"
            target.write_bytes(await response.body())
            image.local_path = str(target)
        except Exception:
            LOGGER.exception("图片下载异常: %s", image.original_url)


async def crawl_cbp(*, output_dir: str | Path = "data", max_articles: int | None = None,
                    max_pages: int | None = None, keywords: tuple[str, ...] = DEFAULT_KEYWORDS,
                    interval: float = 1.5, include_content: bool = False,
                    headless: bool = True, slow_mo: float = 0,
                    recent_days: int = 30) -> dict:
    """创建任务记录后抓取；新闻和图片写数据库，同时保留文件备份。"""
    adapter = SiteAdapter(
        country="US", site="CBP", list_url=DEFAULT_URL, keywords=keywords,
        parse_listing=parse_listing_html, parse_article=parse_article_html,
        normalize_url=lambda url, base: __import__("crawlers.cbp", fromlist=["normalize_url"]).normalize_url(url, base),
        page_url=lambda page_no: DEFAULT_URL if page_no == 0 else _page_url(f"?page={page_no}", DEFAULT_URL),
        matches_body=matches_keywords,
    )
    with SessionLocal() as db:
        site = ensure_cbp_source(db)
        db.commit()
        source_site_id = site.id
    return await run_managed_site_crawl(
        adapter, source_site_id, output_dir=output_dir, max_articles=max_articles,
        max_pages=max_pages, interval=interval, include_content=include_content,
        headless=headless, slow_mo=slow_mo, recent_days=recent_days,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 CBP 官方新闻")
    parser.add_argument("--max-articles", type=int, default=None,
                        help="最多处理文章数；不填写时自动模式不限制数量")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="手动限制页数；不填写时每次按最近天数自动翻页")
    parser.add_argument("--recent-days", "--initial-days", dest="recent_days", type=int,
                        default=int(os.getenv("CBP_RECENT_DAYS", os.getenv("CBP_INITIAL_DAYS", "30"))),
                        help="每次自动抓取的最近天数，默认 30；旧参数 --initial-days 仍可用")
    parser.add_argument("--interval", type=float, default=float(os.getenv("CBP_INTERVAL", "1.5")))
    parser.add_argument("--output-dir", default=os.getenv("CBP_OUTPUT_DIR", "data"))
    parser.add_argument("--keywords", default=os.getenv("CBP_KEYWORDS", ",".join(DEFAULT_KEYWORDS)))
    parser.add_argument("--include-content", action="store_true", help="标题未命中时也匹配列表摘要关键词")
    parser.add_argument("--headed", action="store_true", help="显示 Chromium 浏览器窗口")
    parser.add_argument("--slow-mo", type=float, default=float(os.getenv("CBP_SLOW_MO", "0")),
                        help="每个 Playwright 操作额外等待毫秒数")
    parser.add_argument("--log-file", default=os.getenv("CBP_LOG_FILE", "data/cbp.log"))
    args = parser.parse_args()
    configure_logging(os.getenv("LOG_LEVEL", "INFO"), args.log_file)
    summary = await crawl_cbp(
        output_dir=args.output_dir, max_articles=args.max_articles, max_pages=args.max_pages,
        keywords=tuple(args.keywords.split(",")), interval=args.interval,
        include_content=args.include_content, headless=not args.headed,
        slow_mo=args.slow_mo, recent_days=args.recent_days,
    )
    print(summary)
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

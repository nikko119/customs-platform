"""站点通用任务入口：抓取范围、任务状态和数据库保存。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.core.database import SessionLocal
from app.models import CrawlTask
from app.services.article_persistence import get_source_site, upsert_crawled_article
from crawlers.engine import run_site_crawl
from crawlers.site import CrawlCallbacks, CrawlOptions, SiteAdapter

LOGGER = logging.getLogger(__name__)


def resolve_crawl_plan(*, requested_max_pages: int | None,
                       recent_days: int = 30, now: datetime | None = None) -> tuple[int | None, datetime | None, str]:
    """自动任务每次抓最近 N 天；显式页数仍按手动任务处理。"""
    if requested_max_pages is not None:
        return requested_max_pages, None, "MANUAL"
    # 列表只有发布日期，窗口起点按当天零点比较，避免漏掉边界日新闻。
    cutoff = (now or datetime.now()) - timedelta(days=max(1, recent_days))
    return None, cutoff.replace(hour=0, minute=0, second=0, microsecond=0), "RECENT_WINDOW"


async def run_managed_site_crawl(
    adapter: SiteAdapter, source_site_id: int, *, output_dir: str | Path,
    max_articles: int | None = None, max_pages: int | None = None,
    interval: float = 1.5, include_content: bool = False,
    headless: bool = True, slow_mo: float = 0, recent_days: int = 30,
) -> dict:
    """新站点传入适配器及其数据库 ID，复用任务记录与 URL/Hash 入库。"""
    with SessionLocal() as db:
        site = get_source_site(db, source_site_id)
        if site.site_code != adapter.site or site.country.code != adapter.country:
            raise ValueError(f"站点 {source_site_id} 与适配器 {adapter.country}/{adapter.site} 不匹配")
        effective_pages, published_after, mode = resolve_crawl_plan(
            requested_max_pages=max_pages, recent_days=recent_days,
        )
        task = CrawlTask(source_site_id=site.id, status="RUNNING", max_pages=effective_pages,
                         max_articles=max_articles, crawl_mode=mode, started_at=datetime.now())
        db.add(task)
        db.commit()
        task_id = task.id

    def persist(article, raw_html_path: str) -> str:
        with SessionLocal() as db:
            site = get_source_site(db, source_site_id)
            outcome = upsert_crawled_article(db, site, article, raw_html_path)
            db.commit()
            return outcome

    try:
        summary = await run_site_crawl(
            adapter,
            CrawlOptions(output_dir=Path(output_dir), max_pages=effective_pages,
                         max_articles=max_articles, published_after=published_after,
                         crawl_mode=mode, interval=interval, include_content=include_content,
                         headless=headless, slow_mo=slow_mo),
            CrawlCallbacks(persist_article=persist),
        )
    except Exception as exc:
        LOGGER.exception("站点 %s 抓取失败", source_site_id)
        summary = {"discovered": 0, "selected": 0, "filtered": 0, "date_filtered": 0,
                   "pages_visited": 0, "crawl_mode": mode, "body_filtered": 0,
                   "success": 0, "new": 0, "updated": 0, "unchanged": 0, "errors": [str(exc)]}

    with SessionLocal() as db:
        task = db.get(CrawlTask, task_id)
        task.status = "FAILED" if summary["errors"] else "SUCCESS"
        task.max_pages = summary.get("pages_visited", task.max_pages)
        task.discovered_count = summary["discovered"]
        task.filtered_count = summary["filtered"]
        task.body_filtered_count = summary["body_filtered"]
        task.date_filtered_count = summary.get("date_filtered", 0)
        task.success_count = summary["success"]
        task.new_count = summary["new"]
        task.updated_count = summary["updated"]
        task.unchanged_count = summary["unchanged"]
        task.failed_count = len(summary["errors"])
        task.error_message = "\n".join(summary["errors"])[:60000] or None
        task.finished_at = datetime.now()
        db.commit()
    summary["task_id"] = task_id
    return summary

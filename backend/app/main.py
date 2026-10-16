"""FastAPI 入口，同时提供一个用于查看抓取结果的简易页面。"""
from __future__ import annotations
import json
import os
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.crud import router as database_router
from app.api.export import router as export_router
from app.core.api_access import guard_remote_api
from app.core.database import SessionLocal, get_db
from app.models import Article, SourceSite
from app.services.article_persistence import import_all_legacy_json

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "backend" / "data"
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
DATA_ROOT.mkdir(parents=True, exist_ok=True)

def current_output_dir() -> Path:
    """找到抓取输出目录，优先使用 CBP_OUTPUT_DIR，否则选择最近结果。"""
    configured = os.getenv("CBP_OUTPUT_DIR")
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_absolute() else PROJECT_ROOT / "backend" / candidate
    if (DATA_ROOT / "articles").is_dir():
        return DATA_ROOT
    candidates = [p for p in DATA_ROOT.iterdir() if p.is_dir() and (p / "articles").is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else DATA_ROOT

app = FastAPI(title="Customs News Platform")
app.middleware("http")(guard_remote_api)
app.include_router(database_router)
app.include_router(export_router)


@app.on_event("startup")
def import_legacy_json_on_startup() -> None:
    """服务启动时只补导入已有 JSON，不删除数据库数据。"""
    try:
        with SessionLocal() as db:
            imported = import_all_legacy_json(db, DATA_ROOT)
            if imported:
                LOGGER.info("已将 %s 篇历史 JSON 导入数据库", imported)
    except Exception:
        # 首次启动尚未执行迁移时不阻断网页服务，日志会保留原因。
        LOGGER.exception("导入历史 JSON 失败，请先执行 alembic upgrade head")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/articles")
def list_articles(
    q: str | None = Query(default=None, max_length=200),
    source_site_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """从数据库按标题和来源分页读取新闻。"""
    filters = []
    if q and q.strip():
        # 标题搜索使用包含匹配，方便只输入标题中的一部分。
        filters.append(Article.title.ilike(f"%{q.strip()}%"))
    if source_site_id is not None:
        filters.append(Article.source_site_id == source_site_id)

    count_query = select(func.count(Article.id)).where(*filters)
    total = db.scalar(count_query) or 0
    rows = db.scalars(
        select(Article)
        .options(selectinload(Article.images), selectinload(Article.source_site).selectinload(SourceSite.country))
        .where(*filters)
        .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    articles = []
    for row in rows:
        item = {"id": row.id, "source_site_id": row.source_site_id,
                "country": row.source_site.country.code, "site": row.source_site.site_code,
                "source_url": row.source_url,
                "title": row.title, "author": row.author, "published_at": row.published_at,
                "language": row.language, "content": row.content, "cleaned_content": row.cleaned_content,
                "content_hash": row.content_hash,
                "crawl_status": row.crawl_status, "crawled_at": row.last_crawled_at, "images": [], "_images": []}
        for image in row.images:
            image_data = {"original_url": image.original_url, "local_path": image.local_path or "",
                          "alt": image.alt or "", "position": image.position}
            item["images"].append(image_data)
            local = Path(image.local_path or "")
            if not local.exists():
                local = PROJECT_ROOT / "backend" / local
            if local.exists():
                try:
                    relative = local.resolve().relative_to(DATA_ROOT.resolve()).as_posix()
                    item["_images"].append({**image_data, "url": "/files/" + relative})
                except ValueError:
                    pass
        articles.append(item)
    return {"data_dir": str(current_output_dir()), "source": "database", "count": total,
            "limit": limit, "offset": offset, "articles": articles}

@app.get("/api/articles/{filename}")
def get_article(filename: str):
    path = current_output_dir() / "articles" / filename
    if path.suffix != ".json" or not path.is_file():
        raise HTTPException(status_code=404, detail="文章不存在")
    return json.loads(path.read_text(encoding="utf-8"))

app.mount("/files", StaticFiles(directory=str(DATA_ROOT)), name="files")
app.mount("/assets", StaticFiles(directory=str(FRONTEND_ROOT)), name="assets")

@app.get("/", response_class=FileResponse)
@app.get("/news", response_class=FileResponse)
@app.get("/tasks", response_class=FileResponse)
@app.get("/prompts", response_class=FileResponse)
def dashboard():
    return FileResponse(FRONTEND_ROOT / "index.html")

"""数据库连接配置。"""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import BigInteger, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from dotenv import load_dotenv

# 从 backend/.env 读取本地配置；系统环境变量优先级更高，不会覆盖已有设置。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# 从 backend/.env 读取本地配置；系统环境变量优先，不覆盖已有设置。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def get_database_url() -> str:
    """SQLite 文件固定在 backend/data，避免从其他工作目录启动时换数据库。"""
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured
    backend_root = Path(__file__).resolve().parents[2]
    data_dir = backend_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + str(data_dir / "customs_platform.db").replace("\\", "/")


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True, "pool_recycle": 1800}


DATABASE_URL = get_database_url()
engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(Session, "before_flush")
def assign_sqlite_bigint_ids(session: Session, flush_context, instances) -> None:
    """旧 SQLite 表的 BIGINT 主键不支持自增，插入时分配下一个 ID。"""
    if session.get_bind().dialect.name != "sqlite":
        return
    connection = session.connection()
    next_ids: dict[str, int] = {}
    for item in session.new:
        if getattr(item, "id", None) is not None:
            continue
        column = item.__table__.c.get("id")
        if column is None or not isinstance(column.type, BigInteger):
            continue
        table_key = item.__table__.fullname
        # 同一次 flush 可能同时新增一篇文章和多张图片，必须在内存中递增，不能每次都取同一个 max(id)+1。
        if table_key not in next_ids:
            next_ids[table_key] = int(connection.scalar(
                select(func.coalesce(func.max(column), 0) + 1).select_from(item.__table__)
            ) or 1)
        item.id = next_ids[table_key]
        next_ids[table_key] += 1


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖使用的数据库会话。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

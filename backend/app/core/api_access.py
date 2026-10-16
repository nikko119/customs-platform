"""本机管理可直接访问；跨电脑请求必须携带用途对应的 API Key。"""
from __future__ import annotations

import hmac
import ipaddress
import os

from fastapi import Request
from fastapi.responses import JSONResponse


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def guard_remote_api(request: Request, call_next):
    path = request.url.path
    if not (path.startswith("/api/") or path == "/files" or path.startswith("/files/")):
        return await call_next(request)
    host = request.client.host if request.client else ""
    # TestClient 使用固定的 testclient 地址；本机访问还要求 Host 为回环地址，
    # 避免反向代理把外部请求转成本机连接后绕过鉴权。
    if host == "testclient" or (_is_loopback(host) and _is_loopback(request.url.hostname or "")):
        return await call_next(request)

    supplied = request.headers.get("X-API-Key", "")
    admin_key = os.getenv("ADMIN_API_KEY", "").strip()
    export_key = os.getenv("EXPORT_API_KEY", "").strip()
    if admin_key and export_key and hmac.compare_digest(admin_key, export_key):
        return JSONResponse(status_code=503, content={"detail": "请为读取与管理接口设置不同的 API Key"})
    is_admin = bool(admin_key and supplied and hmac.compare_digest(supplied, admin_key))
    is_export = bool(export_key and supplied and hmac.compare_digest(supplied, export_key))
    export_path = path == "/api/v1/rewritten-articles"
    if (export_path and (is_admin or is_export)) or (not export_path and is_admin):
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "跨电脑访问需要有效的 X-API-Key"},
                        headers={"WWW-Authenticate": "ApiKey"})

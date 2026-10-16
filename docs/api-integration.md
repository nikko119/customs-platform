# 官网获取改写稿

带教系统使用只读接口 `GET /api/v1/rewritten-articles`。它不触发抓取或模型调用，只读取已经保存的稿件；每篇原文仅返回最新一次真实模型成功改写的版本。模拟稿、失败稿、原文更新后尚未重新改写的旧稿都不会出现在结果中。

## 本机验证

在 `backend` 目录启动服务：

```powershell
py -3.13 -m uvicorn app.main:app --host 127.0.0.1 --port 8015
```

浏览器打开 `http://127.0.0.1:8015/docs` 可查看接口字段。本机可直接访问：

```text
http://127.0.0.1:8015/api/v1/rewritten-articles?limit=5&offset=0
```

没有真实改写稿时，返回 `{"count":0,"limit":5,"offset":0,"articles":[]}`，这不是接口故障。

## 跨电脑调用

在服务端的 `backend/.env` 中分别配置两把不同的随机密钥：

```dotenv
EXPORT_API_KEY=只读调用密钥
ADMIN_API_KEY=管理调用密钥
```

两把密钥必须不同，否则跨电脑 API 会返回 HTTP 503。不要把真实密钥写进 `.env.example` 或 Git。服务需要监听可访问的网卡地址；`127.0.0.1` 只能从运行服务的电脑访问。正式跨电脑使用时请通过 HTTPS 或可信的内网网关连接，避免 API Key 在网络中明文传输。反向代理应保留原始 Host，并由网关限制后台页面的访问。

带教只需要 `EXPORT_API_KEY`。PowerShell 示例：

```powershell
$headers = @{ 'X-API-Key' = '带教获得的只读密钥' }
Invoke-RestMethod -Uri 'https://你的服务地址/api/v1/rewritten-articles?limit=20&offset=0' -Headers $headers
```

`EXPORT_API_KEY` 只能访问改写稿只读接口，不能读取管理接口、原始新闻、提示词，也不能新增、修改或删除记录。`ADMIN_API_KEY` 可以访问管理 API，应仅由平台管理员保管。未配置密钥时，本机管理仍能运行，但跨电脑 API 请求会返回 HTTP 401。

## 查询参数

| 参数 | 说明 |
| --- | --- |
| `limit` | 每页篇数，默认 20，最多 100 |
| `offset` | 从第几条开始，默认 0；下一页传上一页的 `offset + limit` |
| `source_site_id` | 可选，只要指定站点的新闻 |
| `country` | 可选，国家代码，如 `US` 或 `CA` |
| `updated_since` | 可选，只取改写稿在此时间后新增或修改的结果，使用 ISO 8601 时间 |

响应的 `count` 是筛选后的总篇数，`articles` 是当前页。每项包含 `article_id`、`rewrite_id`、`country`、`site`、`source_site_id`、`source_url`、`published_at`、中文 `title` 和 `content`、`images`、`model_name`、`prompt_version`、`rewritten_at` 和 `updated_at`。图片项提供官网 `original_url`、`alt` 和 `position`；官网使用图片前应自行确认来源站点的使用条件与可访问性。

批量同步时，从 `offset=0` 开始逐页读取，直到返回的 `articles` 数量小于 `limit`。新稿可能改变分页顺序，定期同步时按 `rewrite_id` 去重；`updated_since` 可减少重复传输。原文更新后旧改写稿会暂时从接口消失，重新改写后再次出现。

## 新增信息源

数据库中的 `countries` 和 `source_sites` 是通用结构。新站点需要根据其真实 HTML 编写列表/详情解析器与分页 URL 函数，组成 `SiteAdapter`，再调用 `run_managed_site_crawl(adapter, source_site_id, ...)`。通用入口负责抓取任务记录、首次时间窗口、文章和图片入库及 URL/Hash 去重；它会检查适配器中的国家、站点代码与数据库记录一致。不能只填写站点 URL 就自动解析任意网页。

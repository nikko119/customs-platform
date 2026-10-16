# 官网读取改写稿 API 使用文档

本文可直接交给调用接口的同事。代码仓库存放程序；新闻和改写结果保存在运行服务的电脑上。接口只读取已经保存的稿件，不会触发抓取、翻译或改写。

## 交给调用方的信息

| 项目 | 内容 |
| --- | --- |
| 方法 | `GET` |
| 接口路径 | `/api/v1/rewritten-articles` |
| 局域网完整地址示例 | `http://192.168.0.74:8015/api/v1/rewritten-articles` |
| 鉴权请求头 | `X-API-Key: <只读密钥>` |
| 响应格式 | UTF-8 JSON |

`192.168.0.74` 是服务电脑在 2026-10-16 检测到的局域网 IP，仅供当前网络参考；发送前用 `ipconfig` 再确认。调用方需要完整地址和 `EXPORT_API_KEY` 的值，不需要管理密钥 `ADMIN_API_KEY`。密钥请私下发送，不要写进 Git 仓库、网页 JavaScript、公开文档或 URL。

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

服务提供者在 `backend` 目录运行以下命令，并保持终端、电脑和网络处于运行状态：

```powershell
py -3.13 -m uvicorn app.main:app --host 0.0.0.0 --port 8015
```

`0.0.0.0` 是服务监听地址，不是调用方填写的主机地址。Python 不是 3.13 时，请换成实际安装的 Python 3.11+ 命令。每次修改 `.env` 后需要重启服务。电脑关机、休眠或服务终止时，接口不可用；IP 改变后也要重新通知调用方。

两台电脑应处于可互通的局域网。在调用方电脑上先运行 `Test-NetConnection 192.168.0.74 -Port 8015`，将 IP 换成服务电脑的实际地址。`TcpTestSucceeded: True` 表示端口可达。如同网仍不通，检查 Windows 防火墙。确需放行时，可由管理员在服务电脑的 PowerShell 中运行：

```powershell
New-NetFirewallRule -DisplayName "Customs API LAN 8015" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8015 -RemoteAddress LocalSubnet -Profile Any
```

局域网 HTTP 仅适合可信内网联调。异地调用方无法直接访问 `192.168.x.x` 地址；需要双方可互通的 VPN，或将服务部署到有 HTTPS 的服务器。不要为此直接把管理后台端口开放到公网。

带教只需要 `EXPORT_API_KEY`。PowerShell 示例：

```powershell
$headers = @{ 'X-API-Key' = '带教获得的只读密钥' }
$result = Invoke-RestMethod -Uri 'http://192.168.0.74:8015/api/v1/rewritten-articles?limit=5&offset=0' -Headers $headers
$result.count
$result.articles | Select-Object article_id, rewrite_id, title, updated_at
```

请将示例 IP 换成服务提供者确认的实际地址。也可用 Postman：方法选 `GET`，输入完整 URL，在 Headers 中添加 `X-API-Key`。直接把地址粘贴进浏览器地址栏会返回 HTTP 401，因为地址栏没有附带请求头。调用方应从自己的**服务端程序**请求，避免只读密钥暴露在公开网页中。`GET /health` 可以检测服务是否运行，但不能代替导出接口的鉴权和数据测试。

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

`article_id` 标识原始新闻，`rewrite_id` 标识这次改写版本。`published_at` 可能为 `null`。图片只提供官网原始 URL，不提供平台本地图片路径，也不保证第三方网站可以直接嵌入。时间字段按服务端实际返回的日期时间字符串处理，不要自行假定一定带时区。无符合条件稿件时，接口仍返回 HTTP 200，例如 `{"count":0,"limit":5,"offset":0,"articles":[]}`。

批量同步时，从 `offset=0` 开始逐页读取，直到返回的 `articles` 数量小于 `limit`。新稿可能改变分页顺序，定期同步时按 `rewrite_id` 去重；`updated_since` 可减少重复传输。原文更新后旧改写稿会暂时从接口消失，重新改写后再次出现。

`updated_since` 只返回当前符合导出条件且在该时间之后更新的稿件，**不会发送删除通知**。如果调用方需要自己的库与当前可用稿件严格一致，应定期进行全量核对。分页时建议每篇以 `article_id` 作为原新闻标识，以 `rewrite_id` 区分版本；当新稿在同步期间插入列表时，按 `rewrite_id` 去重。

## Python 调用示例

调用方在自己的电脑上设置环境变量 `CUSTOMS_EXPORT_API_KEY`，不要把真实密钥写入代码。以下示例使用 Python 标准库分页读取：

```python
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

base_url = "http://192.168.0.74:8015/api/v1/rewritten-articles"
headers = {"X-API-Key": os.environ["CUSTOMS_EXPORT_API_KEY"]}
limit = 20
offset = 0

while True:
    url = f"{base_url}?{urlencode({'limit': limit, 'offset': offset})}"
    with urlopen(Request(url, headers=headers), timeout=15) as response:
        page = json.load(response)

    for article in page["articles"]:
        print(article["rewrite_id"], article["title"])
        # 在这里按 article_id 和 rewrite_id 保存到调用方自己的数据库。

    if len(page["articles"]) < limit:
        break
    offset += limit
```

示例地址也需换成服务提供者确认的地址。若请求返回 HTTP 401，检查 `X-API-Key`；HTTP 503 表示服务端两把密钥相同；HTTP 422 通常是查询参数格式或范围错误，例如 `limit=0` 或 `limit=101`。连接超时或拒绝连接时，检查服务进程、IP、端口、网络和防火墙。HTTP 200 但 `articles` 为空时，先去掉筛选条件，再确认是否已有真实模型成功改写稿。

## 新增信息源

数据库中的 `countries` 和 `source_sites` 是通用结构。新站点需要根据其真实 HTML 编写列表/详情解析器与分页 URL 函数，组成 `SiteAdapter`，再调用 `run_managed_site_crawl(adapter, source_site_id, ...)`。通用入口负责抓取任务记录、首次时间窗口、文章和图片入库及 URL/Hash 去重；它会检查适配器中的国家、站点代码与数据库记录一致。不能只填写站点 URL 就自动解析任意网页。

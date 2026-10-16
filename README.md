# 集运行业官方新闻平台

第一阶段实现美国 CBP 新闻的手动抓取、关键词筛选、图片下载、SQLite/MySQL 持久化、英文正文清洗、真实模型中文翻译与改写，以及供外部系统读取最终改写稿的 API。后台目前是 FastAPI 提供的轻量静态页面；尚未建设 Vue 管理端，也没有自动定时抓取。

## 安装

需要 Python 3.11+。在项目根目录执行：

Windows PowerShell：

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
alembic upgrade head
```

如果电脑没有 Python 3.13，请把 `py -3.13` 换成实际安装的 Python 3.11+ 命令。macOS/Linux：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
alembic upgrade head
```

默认数据库为 `backend/data/customs_platform.db`，重启服务不会清空数据。连接 MySQL 5.7 时，在 `backend/.env` 中设置 `DATABASE_URL=mysql+pymysql://用户:密码@主机:3306/customs_platform?charset=utf8mb4`，创建数据库后运行 `alembic upgrade head`。数据库结构及关系见 [数据库文档](backend/docs/database.md)。

## 本地配置

将 `backend/.env.example` 复制为 `backend/.env`，在自己的 `.env` 中填写 `LLM_BASE_URL`、`LLM_API_KEY` 和实际支持的 `LLM_MODEL`。不配置真实模型时，抓取、阅读、清洗和模拟处理仍可使用；真实翻译改写需要有效中转站配置。`.env`、数据库和抓取产物都被 Git 忽略，**不要把密钥发给带教或提交到仓库**。

## 抓取与查看

以下命令都在 `backend` 目录运行。默认每次从第一页开始翻页，抓取最近 30 天内标题及正文均命中关键词的新闻；历史文章会按 URL 和内容 Hash 去重：

```powershell
python -m crawlers.cbp_fetch --output-dir data
```

默认不限制文章篇数。近 30 天可用 `CBP_RECENT_DAYS` 或 `--recent-days 30` 调整；`--max-articles 30` 则最多处理 30 篇**筛选后的**新闻，并不代表官网最新 30 条。显式设置 `--max-pages` 会改为手动页数模式，不再按日期截取。以前的 `--initial-days` 和 `CBP_INITIAL_DAYS` 暂时仍可用，但建议改用新名称。

浏览器默认使用 `CRAWLER_BROWSER=auto`：依次尝试项目目录 `backend/data/browsers` 中的 Chromium、Playwright 默认 Chromium 和系统已安装的 Google Chrome。浏览器启动失败会记录原因并自动尝试下一项；全部失败时任务会标记为失败，命令行也会返回非零退出码。如果想优先使用 Google Chrome，在 `backend/.env` 中设置 `CRAWLER_BROWSER=chrome`。没有任何可用浏览器时运行 `python -m playwright install chromium`；也可用 `PLAYWRIGHT_BROWSERS_PATH` 或 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定浏览器。`requirements.txt` 固定了已验证的 Playwright 版本，重新安装依赖后应按安装步骤重新安装配套 Chromium。Chrome 回退只处理浏览器启动问题，CBP 返回 403 或网页结构变化仍会如实记为抓取失败。

想看到 Playwright 浏览器过程，可先小范围测试：

```powershell
python -m crawlers.cbp_fetch --headed --slow-mo 300 --max-pages 1 --max-articles 1 --output-dir data\visible-test
```

启动页面：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8015
```

打开 `http://127.0.0.1:8015/`。左侧导航分别进入总览、新闻管理、抓取任务和提示词模板。新闻每页显示 5 篇，可查看原文、清洗稿、中文翻译、改写结果，并手动点击真实模型处理。抓取任务每 5 秒刷新；长错误在详情弹窗中显示。端口被占用时将命令和浏览器地址中的 `8015` 同时换成空闲端口。

抓取原始 HTML、截图、JSON、图片、历史索引和日志在 `backend/data/`；数据库中的新闻不会因更换输出目录或重启服务而丢失。关键词通过 `CBP_KEYWORDS` 或 `--keywords cargo,shipping,import` 配置；先匹配标题，再按正文关键词二次筛选。`--max-pages` 和 `--max-articles` 可用于小范围测试。

## 带教读取改写稿

本机试用：`http://127.0.0.1:8015/api/v1/rewritten-articles?limit=5&offset=0`。接口每篇只返回当前原文对应的最新真实模型成功改写稿；模拟稿及原文更新后的旧稿不会返回。跨电脑调用需要两把不同的 `EXPORT_API_KEY`（只读）与 `ADMIN_API_KEY`（管理），并在请求头发送 `X-API-Key`。完整字段、分页、筛选和 PowerShell 调用示例见 [官网 API 对接说明](docs/api-integration.md)。

新增其他国家或站点时，需要基于该站点真实 HTML 编写解析器，组合 `SiteAdapter` 后复用通用抓取入口；见 [抓取架构](docs/crawler-architecture.md)。

## 验证

```powershell
cd backend
python -m pytest -q
```

测试使用内存 SQLite 和离线 HTML 样本，不会调用真实模型，也不会抓取 CBP。API 文档位于 `http://127.0.0.1:8015/docs`。真实网站能否访问仍取决于运行电脑的网络与 CBP 当前访问策略。

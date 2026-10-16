# 数据库结构和迁移

第一期使用 SQLAlchemy 2、Alembic 和 PyMySQL，包含 8 张表：

| 表 | 作用 |
| --- | --- |
| `countries` | 国家，例如 US |
| `source_sites` | 官方站点和抓取规则 |
| `news_articles` | 原始新闻，按站点和规范化 URL 唯一 |
| `news_images` | 新闻图片及本地路径 |
| `prompts` | 提示词及版本 |
| `news_processed` | AI 改写版本，保留原文 |
| `crawl_tasks` | 抓取任务和统计 |
| `llm_tasks` | AI 处理任务和错误 |

## 本地结构验证

未配置 `DATABASE_URL` 时默认使用 SQLite，方便开发者检查表结构：

```powershell
cd backend
alembic upgrade head
```

数据库文件为 `backend/data/customs_platform.db`。

## MySQL 5.7

先在 MySQL 中创建数据库（字符集必须是 `utf8mb4`）：

```sql
CREATE DATABASE customs_platform DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

PowerShell 设置连接地址：

```powershell
$env:DATABASE_URL="mysql+pymysql://用户名:密码@127.0.0.1:3306/customs_platform?charset=utf8mb4"
alembic upgrade head
```

不要把真实密码提交到 `.env.example` 或代码仓库。抓取程序会在每次任务开始时写入 `crawl_tasks`，成功抓取的新闻写入 `news_articles`，正文图片写入 `news_images`；同一站点的规范化 URL 用于去重，内容 Hash 用于判断新增、更新或未变化。

升级到最新任务字段后，继续执行：

```powershell
alembic upgrade head
```

最新任务表还记录 `crawl_mode`（首次近月、后续第一页或手动限制）和 `date_filtered_count`（窗口外旧记录数）。

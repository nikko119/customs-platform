# 多国家、多站点抓取结构

当前实际入口是 `backend/crawlers/runner.py` 中的 `run_managed_site_crawl(adapter, source_site_id, ...)`：它按站点 ID 创建抓取任务、决定首次/增量范围、保存新闻和图片、回写任务统计。`cbp_fetch.py` 只组装 CBP 的 `SiteAdapter` 并调用这个入口；新站点也应调用同一个入口。网页结构与分页规则仍需基于新站点的真实 HTML 单独编写和测试。

当前抓取流程分成两层：

- `backend/crawlers/engine.py` 是通用抓取引擎，负责 Playwright 访问、分页循环、原始 HTML 和截图保存、URL 去重、标题及正文关键词筛选、图片下载、JSON 保存、历史索引和异常统计。
- `backend/crawlers/site.py` 定义站点适配器接口。每个网站提供国家代码、站点代码、列表分页 URL、列表解析器、详情解析器、URL 规范化方法和正文关键词判断方法。
- `backend/crawlers/cbp.py` 只保存 CBP 的页面结构解析规则；`cbp_fetch.py` 负责把 CBP 适配器接入通用引擎和数据库任务。

## 抓取范围策略

`cbp_fetch` 会按 `source_site` 的成功任务选择范围：站点第一次使用自动规则时使用 `INITIAL_WINDOW`，从第一页开始翻页，保留列表发布日期在最近 `CBP_INITIAL_DAYS`（默认 30 天）内的记录；遇到整页日期都早于窗口时停止。已有完整成功的自动任务后使用 `INCREMENTAL_FIRST_PAGE`，只访问第一页。首次任务失败、没有成功文章或使用了 `--max-articles` 限量测试，都不会让站点进入增量模式；升级前的旧任务也不会阻止首次近月补抓。显式传入 `--max-pages` 会使用 `MANUAL` 页数模式。

以后新增英国或加拿大站点时，建议按以下步骤处理：

1. 新建对应解析模块，例如 `crawlers/uk_gov.py`，只处理该网站的 HTML 结构。
2. 创建 `SiteAdapter`，填入列表地址、分页规则、关键词和解析函数。
3. 复用 `run_site_crawl`，通过数据库中的 `source_sites` 记录保存文章和抓取任务。
4. 为列表解析、正文区域隔离、分页和 URL 规范化增加离线 HTML 测试。

新增站点不需要复制 Playwright、去重、图片下载和任务统计代码；不同网站的选择器、日期格式和分页方式由各自适配器隔离。

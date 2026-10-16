# 清洗、翻译和改写流程

## 数据如何保存

- 英文原文保存在 `news_articles.content`，不被处理流程覆盖。
- 清洗后的英文保存在 `news_articles.cleaned_content`。
- 每次中文翻译单独保存在 `news_translations`，记录源语言、目标语言、原文 Hash、提示词版本和模型名称。
- 每次中文改写单独保存在 `news_processed`，并关联对应的译文、改写提示词版本和模型名称。
- `llm_tasks` 分别记录 `TRANSLATE` 和 `REWRITE` 两个处理阶段。

## 模拟流程

页面可以维护翻译模板和改写模板。选择新闻后，点击“清洗正文”，再分别选择翻译模板和改写模板，点击“模拟处理”。

真实模型流程已经接入；模拟译文仍会明确提示“以下仍为英文清洗稿”，模拟结果只验证数据保存和任务关联，不是真正的中文翻译，也不会调用或消耗 API 额度。

```powershell
cd backend
alembic upgrade head
py -3.13 -m uvicorn app.main:app --host 127.0.0.1 --port 8015
```

## 真实模型调用

项目使用 LangChain 的 `ChatOpenAI` 连接 OpenAI 兼容中转站，顺序调用两次：

1. 清洗后的英文正文和 `TRANSLATE` 提示词用于翻译，结果保存到 `news_translations`。
2. 中文译文和 `REWRITE` 提示词用于改写，结果保存到 `news_processed`。

正文清洗会移除 CBP 正文末尾以“Follow the Director of CBP”等形式出现的社交账号推广段；抓取的正文图片仍单独保存并展示。翻译和改写要求使用自然、通顺、符合中国读者习惯的表达，同时保留原文事实、数字、日期、地点和机构信息。

中文翻译和改写版本分别保存，原始英文 `news_articles.content` 不会被覆盖。页面上的“模拟翻译 + 改写”不联网、不扣额度；“真实模型翻译 + 改写”会请求中转站并按其规则消耗额度。

### 本机配置

在 `backend` 目录复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

编辑 `backend/.env`，填写中转站提供的真实 API Key 和准确模型 ID：

```dotenv
LLM_BASE_URL=http://192.168.0.42:8080/v1
LLM_API_KEY=填写你自己的密钥
LLM_MODEL=gpt-6-luna
```

`192.168.0.42` 是局域网地址，运行 FastAPI 的电脑必须能访问它。不要把 `.env` 提交到 Git，也不要把 API Key 发到聊天或写入 `.env.example`。模型 ID 是否确为 `gpt-6-luna`，以及中转站是否支持标准 Chat Completions 请求和 JSON 文本输出，需要以管理员提供的信息为准。

安装依赖并启动：

```powershell
cd backend
py -3.13 -m pip install -r requirements.txt
alembic upgrade head
py -3.13 -m uvicorn app.main:app --host 127.0.0.1 --port 8015
```

打开新闻详情，分别选择启用的翻译模板和改写模板，再点击“真实模型翻译 + 改写”。建议先用一篇短新闻测试。调用失败时可在启动服务的终端查看日志，数据库 `llm_tasks` 也会记录失败阶段。

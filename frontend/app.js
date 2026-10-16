const API = "/api/v1";
const PAGE_SIZE = 5;
const page = ({ "/": "dashboard", "/news": "news", "/tasks": "tasks", "/prompts": "prompts" })[location.pathname.replace(/\/$/, "") || "/"] || "dashboard";
const titles = {
  dashboard: ["总览", "查看采集与内容处理进度"],
  news: ["新闻管理", "搜索并查看原文、清洗、翻译与改写"],
  tasks: ["抓取任务", "查看每次运行的状态和统计"],
  prompts: ["提示词模板", "管理翻译与改写模板版本"],
};
const state = { offset: 0, total: 0, articles: [], selectedId: null, articleTab: "original", translations: [], versions: [], prompts: [], tasks: [], taskTimer: null };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const dateText = (value) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
const shortDate = (value) => value ? String(value).slice(0, 10) : "日期未提供";
const statusLabel = { SUCCESS: "成功", FAILED: "失败", RUNNING: "运行中", PENDING: "待处理", ACTIVE: "启用", INACTIVE: "停用", MOCK: "模拟" };
const statusBadge = (status) => `<span class="badge ${String(status).toLowerCase()}">${escapeHtml(statusLabel[status] || status || "未知")}</span>`;

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("is-error", error);
  node.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("visible"), 4500);
}

async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  } catch (error) {
    $("#connection-state").innerHTML = "<i></i>连接失败";
    $("#connection-state").classList.add("offline");
    throw new Error(`无法连接后端：${error.message}`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : `请求失败：HTTP ${response.status}`);
  }
  $("#connection-state").innerHTML = "<i></i>已连接";
  $("#connection-state").classList.remove("offline");
  return response.status === 204 ? null : response.json();
}

function stat(label, number, note = "") {
  return `<div class="surface stat"><div class="stat-label">${label}</div><div class="stat-value">${number}</div>${note ? `<div class="stat-note">${note}</div>` : ""}</div>`;
}

async function loadDashboard() {
  try {
    const [articles, tasks, prompts] = await Promise.all([
      request("/api/articles?limit=1"), request(`${API}/crawl-tasks`), request(`${API}/prompts`),
    ]);
    const latest = tasks[0];
    $("#dashboard-stats").innerHTML = [
      stat("已收录新闻", articles.count, "数据库中保存的文章"),
      stat("抓取任务", tasks.length, latest ? `最近一次：${statusLabel[latest.status] || latest.status}` : "尚无运行记录"),
      stat("新增文章", tasks.reduce((sum, task) => sum + task.new_count, 0), "所有抓取任务累计"),
      stat("提示词版本", prompts.length, "翻译和改写模板"),
    ].join("");
    $("#dashboard-recent-tasks").innerHTML = tasks.length ? tasks.slice(0, 5).map((task) => `
      <div class="recent-task"><span class="recent-id">#${task.id}</span>${statusBadge(task.status)}
      <span>新增 ${task.new_count} · 更新 ${task.updated_count}</span><time>${shortDate(task.started_at || task.created_at)}</time></div>
    `).join("") : '<div class="empty">还没有抓取记录。</div>';
  } catch (error) {
    $("#dashboard-stats").innerHTML = `<div class="surface empty">${escapeHtml(error.message)}</div>`;
    toast(error.message, true);
  }
}

async function loadSources() {
  try {
    const sources = await request(`${API}/source-sites`);
    $("#source-filter").innerHTML = '<option value="">全部信息源</option>' + sources.map((site) => `<option value="${site.id}">${escapeHtml(site.name)}</option>`).join("");
  } catch (error) { toast(error.message, true); }
}

async function loadArticles(keepSelection = false) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.offset) });
  const query = $("#search-query").value.trim();
  if (query) params.set("q", query);
  if ($("#source-filter").value) params.set("source_site_id", $("#source-filter").value);
  $("#news-list").innerHTML = '<div class="empty">正在读取新闻…</div>';
  try {
    const result = await request(`/api/articles?${params}`);
    state.articles = result.articles;
    state.total = result.count;
    $("#news-count").textContent = `共 ${result.count} 篇`;
    $("#news-page-number").textContent = `第 ${Math.floor(state.offset / PAGE_SIZE) + 1} / ${Math.max(1, Math.ceil(result.count / PAGE_SIZE))} 页`;
    $("#news-prev").disabled = state.offset === 0;
    $("#news-next").disabled = state.offset + PAGE_SIZE >= result.count;
    const selected = keepSelection ? state.articles.find((article) => article.id === state.selectedId) : null;
    state.selectedId = selected?.id || state.articles[0]?.id || null;
    $("#news-list").innerHTML = state.articles.length ? state.articles.map((article) => `
      <button type="button" class="news-item ${article.id === state.selectedId ? "active" : ""}" data-article-id="${article.id}">
        <span class="news-item-date">${escapeHtml(shortDate(article.published_at))}</span>
        <strong>${escapeHtml(article.title)}</strong>
        <small>${escapeHtml(article.site || "CBP")} · ${article.cleaned_content ? "已清洗" : "原文"}</small>
      </button>`).join("") : '<div class="empty">没有匹配的新闻。</div>';
    if (state.selectedId) await selectArticle(state.selectedId);
    else $("#article-detail").innerHTML = '<div class="empty">没有可显示的新闻。</div>';
  } catch (error) { $("#news-list").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; toast(error.message, true); }
}

function activePrompt(purpose) {
  return state.prompts.filter((prompt) => prompt.purpose === purpose && prompt.status === "ACTIVE")
    .sort((a, b) => b.version - a.version || b.id - a.id)[0];
}

function promptSelect(purpose, id) {
  const options = state.prompts.filter((prompt) => prompt.purpose === purpose && prompt.status === "ACTIVE");
  const preferred = activePrompt(purpose)?.id;
  return `<select id="${id}" aria-label="${purpose === "TRANSLATE" ? "翻译" : "改写"}模板">${options.map((prompt) => `
    <option value="${prompt.id}" ${prompt.id === preferred ? "selected" : ""}>${escapeHtml(prompt.name)} · v${prompt.version}</option>`).join("")}</select>`;
}

async function selectArticle(id) {
  state.selectedId = id;
  state.articleTab = "original";
  $("#news-list").querySelectorAll("[data-article-id]").forEach((item) => item.classList.toggle("active", Number(item.dataset.articleId) === id));
  $("#article-detail").innerHTML = '<div class="empty">正在读取详情…</div>';
  try {
    [state.translations, state.versions] = await Promise.all([
      request(`${API}/translations?article_id=${id}`), request(`${API}/processed-articles?article_id=${id}`),
    ]);
    renderArticle();
  } catch (error) { $("#article-detail").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; toast(error.message, true); }
}

function articleBody(article) {
  const tab = state.articleTab;
  if (tab === "original") return `<div class="article-content">${escapeHtml(article.content)}</div>${article._images?.length ? `<div class="article-images">${article._images.map((image) => `<figure><img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.alt)}" loading="lazy"><figcaption>${escapeHtml(image.alt)}</figcaption></figure>`).join("")}</div>` : ""}`;
  if (tab === "cleaned") return article.cleaned_content ? `<div class="article-content">${escapeHtml(article.cleaned_content)}</div>` : '<div class="empty">尚未清洗。点击下方“清洗正文”。</div>';
  if (tab === "translated") return state.translations.length ? state.translations.map((item) => `<article class="result-version"><div class="result-meta">#${item.id} · ${escapeHtml(item.model_name || "模拟处理")} · ${dateText(item.created_at)}</div><div class="article-content">${escapeHtml(item.translated_content)}</div></article>`).join("") : '<div class="empty">尚无中文翻译。</div>';
  return state.versions.length ? state.versions.map((item) => `<article class="result-version"><div class="result-meta">#${item.id} · ${escapeHtml(item.model_name || "模拟处理")} · ${dateText(item.created_at)}</div><h4>${escapeHtml(item.title)}</h4><div class="article-content">${escapeHtml(item.content)}</div></article>`).join("") : '<div class="empty">尚无改写结果。</div>';
}

function renderArticle() {
  const article = state.articles.find((item) => item.id === state.selectedId);
  if (!article) return;
  const tabs = [["original", "原文"], ["cleaned", "清洗稿"], ["translated", `中文翻译 ${state.translations.length || ""}`], ["rewritten", `改写结果 ${state.versions.length || ""}`]];
  $("#article-detail").innerHTML = `
    <div class="article-heading"><div><span class="eyebrow">${escapeHtml(article.site || "CBP")} · #${article.id}</span><h2>${escapeHtml(article.title)}</h2>
      <div class="detail-meta">发布 ${escapeHtml(dateText(article.published_at))} · ${escapeHtml(article.author || "发布者未知")}</div></div>
      <a class="link original-link" href="${escapeHtml(article.source_url)}" target="_blank" rel="noopener noreferrer">查看官网原文 ↗</a></div>
    <div class="article-tabs" role="tablist" aria-label="文章版本">${tabs.map(([id, label]) => `<button type="button" role="tab" aria-selected="${state.articleTab === id}" class="${state.articleTab === id ? "active" : ""}" data-tab="${id}">${label}</button>`).join("")}</div>
    <div class="article-body" role="tabpanel">${articleBody(article)}</div>
    <div class="article-actions"><button type="button" data-action="clean">清洗正文</button><span class="action-divider"></span>
      ${promptSelect("TRANSLATE", "translation-prompt")}${promptSelect("REWRITE", "rewrite-prompt")}
      <button type="button" data-action="mock">模拟处理</button><button type="button" class="primary" data-action="process">真实模型翻译 + 改写</button></div>
    <div id="processing-message" class="processing" role="status" hidden></div>`;
}

async function processArticle(action) {
  const article = state.articles.find((item) => item.id === state.selectedId);
  if (!article) return;
  const buttons = $("#article-detail").querySelectorAll(".article-actions button");
  buttons.forEach((button) => button.disabled = true);
  const message = $("#processing-message");
  message.hidden = false;
  message.textContent = action === "process" ? "正在等待真实模型完成翻译和改写，可能需要几分钟，请保持页面打开…" : "正在处理…";
  try {
    if (action === "clean") {
      const updated = await request(`${API}/articles/${article.id}/clean`, { method: "POST" });
      article.cleaned_content = updated.cleaned_content;
      state.articleTab = "cleaned";
    } else {
      const translation_prompt_id = Number($("#translation-prompt").value);
      const rewrite_prompt_id = Number($("#rewrite-prompt").value);
      if (!translation_prompt_id || !rewrite_prompt_id) throw new Error("请先在提示词模板页面启用翻译和改写模板。 ");
      await request(`${API}/articles/${article.id}/${action === "mock" ? "mock-process" : "process"}`, {
        method: "POST", body: JSON.stringify({ translation_prompt_id, rewrite_prompt_id }),
      });
      article.cleaned_content = article.cleaned_content || article.content;
      [state.translations, state.versions] = await Promise.all([
        request(`${API}/translations?article_id=${article.id}`), request(`${API}/processed-articles?article_id=${article.id}`),
      ]);
      state.articleTab = "rewritten";
    }
    renderArticle();
    toast("处理完成，结果已保存到数据库。");
  } catch (error) {
    message.textContent = `处理失败：${error.message}`;
    message.classList.add("is-error");
    buttons.forEach((button) => button.disabled = false);
    toast(error.message, true);
  }
}

async function loadTasks() {
  try {
    state.tasks = await request(`${API}/crawl-tasks`);
    const tasks = state.tasks;
    $("#task-stats").innerHTML = [
      stat("总任务", tasks.length), stat("成功", tasks.filter((task) => task.status === "SUCCESS").length),
      stat("运行中", tasks.filter((task) => task.status === "RUNNING").length),
      stat("失败", tasks.filter((task) => task.status === "FAILED").length),
    ].join("");
    $("#task-updated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} · 每 5 秒刷新`;
    $("#task-rows").innerHTML = tasks.length ? tasks.map((task) => `<tr>
      <td><strong>#${task.id}</strong><small class="cell-sub">站点 ${task.source_site_id}</small></td>
      <td>${statusBadge(task.status)}</td><td>${escapeHtml(task.crawl_mode)}</td>
      <td>${task.discovered_count} / ${task.filtered_count + task.body_filtered_count + task.date_filtered_count}</td>
      <td><b>${task.new_count}</b> / ${task.updated_count}</td>
      <td>${task.unchanged_count} / <span class="${task.failed_count ? "count-failed" : ""}">${task.failed_count}</span></td>
      <td class="nowrap">${escapeHtml(dateText(task.started_at || task.created_at))}</td>
      <td>${task.error_message ? `<button type="button" class="details-link" data-error-id="${task.id}" title="查看完整错误">查看错误</button>` : '<span class="muted">—</span>'}</td>
    </tr>`).join("") : '<tr><td colspan="8" class="empty">还没有抓取任务。</td></tr>';
  } catch (error) { $("#task-rows").innerHTML = `<tr><td colspan="8" class="empty">${escapeHtml(error.message)}</td></tr>`; toast(error.message, true); }
}

async function loadPrompts() {
  try {
    state.prompts = await request(`${API}/prompts`);
    $("#prompt-count").textContent = `${state.prompts.length} 个版本`;
    $("#prompt-list").innerHTML = state.prompts.length ? state.prompts.map((prompt) => `
      <article class="prompt-item">
        <div class="prompt-summary"><div><div class="prompt-name">${escapeHtml(prompt.name)} <span class="version">v${prompt.version}</span></div>
          <div class="muted">${prompt.purpose === "TRANSLATE" ? "翻译" : "改写"} · 更新于 ${escapeHtml(dateText(prompt.updated_at))}</div></div>
          <div class="prompt-controls">${statusBadge(prompt.status)}<button type="button" data-prompt-action="view" data-prompt-id="${prompt.id}">查看</button><button type="button" data-prompt-action="copy" data-prompt-id="${prompt.id}">新版本</button><button type="button" data-prompt-action="toggle" data-prompt-id="${prompt.id}">${prompt.status === "ACTIVE" ? "停用" : "启用"}</button></div></div>
        <div class="prompt-expanded" id="prompt-body-${prompt.id}" hidden><strong>系统提示词</strong><pre>${escapeHtml(prompt.system_prompt)}</pre><strong>用户提示词</strong><pre>${escapeHtml(prompt.user_prompt)}</pre></div>
      </article>`).join("") : '<div class="empty">暂无模板。点击右上角新建。</div>';
  } catch (error) { $("#prompt-list").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; toast(error.message, true); }
}

function openPromptForm(prompt = null) {
  const form = $("#prompt-form");
  form.reset();
  if (prompt) {
    form.elements.name.value = prompt.name;
    form.elements.purpose.value = prompt.purpose;
    form.elements.system_prompt.value = prompt.system_prompt;
    form.elements.user_prompt.value = prompt.user_prompt;
  }
  $("#prompt-form-title").textContent = prompt ? `创建 ${prompt.name} 的新版本` : "新建提示词";
  $("#prompt-form-card").hidden = false;
  $("#prompt-form-card").scrollIntoView({ behavior: "smooth", block: "start" });
  form.elements.name.focus();
}

async function savePrompt(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const name = form.elements.name.value.trim();
  const siblings = state.prompts.filter((prompt) => prompt.name === name);
  const version = Math.max(0, ...siblings.map((prompt) => prompt.version)) + 1;
  const payload = { name, version, purpose: form.elements.purpose.value,
    system_prompt: form.elements.system_prompt.value.trim(), user_prompt: form.elements.user_prompt.value.trim(), status: "ACTIVE" };
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    await request(`${API}/prompts`, { method: "POST", body: JSON.stringify(payload) });
    $("#prompt-form-card").hidden = true;
    await loadPrompts();
    toast(`已保存 ${name} v${version}。`);
  } catch (error) { toast(error.message, true); }
  finally { submit.disabled = false; }
}

function setup() {
  document.title = `${titles[page][0]} · 集运新闻管理台`;
  $("#top-title").textContent = titles[page][0];
  $("#top-subtitle").textContent = titles[page][1];
  $(`#${page}-page`).hidden = false;
  document.querySelectorAll(".nav a").forEach((link) => { if (link.dataset.page === page) { link.classList.add("active"); link.setAttribute("aria-current", "page"); } });
  $("#refresh-page").addEventListener("click", () => location.reload());
  document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => $("#error-dialog").close()));
  $("#error-dialog").addEventListener("click", (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });
  if (page === "dashboard") loadDashboard();
  if (page === "news") {
    loadSources().then(() => loadArticles());
    request(`${API}/prompts`).then((prompts) => { state.prompts = prompts; if (state.selectedId) renderArticle(); }).catch((error) => toast(error.message, true));
    $("#news-search").addEventListener("submit", (event) => { event.preventDefault(); state.offset = 0; loadArticles(); });
    $("#source-filter").addEventListener("change", () => { state.offset = 0; loadArticles(); });
    $("#clear-search").addEventListener("click", () => { $("#search-query").value = ""; $("#source-filter").value = ""; state.offset = 0; loadArticles(); });
    $("#news-prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadArticles(); });
    $("#news-next").addEventListener("click", () => { state.offset += PAGE_SIZE; loadArticles(); });
    $("#news-list").addEventListener("click", (event) => { const item = event.target.closest("[data-article-id]"); if (item) selectArticle(Number(item.dataset.articleId)); });
    $("#article-detail").addEventListener("click", (event) => {
      const tab = event.target.closest("[data-tab]");
      if (tab) { state.articleTab = tab.dataset.tab; renderArticle(); }
      const action = event.target.closest("[data-action]");
      if (action) processArticle(action.dataset.action);
    });
  }
  if (page === "tasks") {
    loadTasks();
    state.taskTimer = setInterval(() => { if (!document.hidden) loadTasks(); }, 5000);
    $("#refresh-tasks").addEventListener("click", loadTasks);
    $("#task-rows").addEventListener("click", (event) => {
      const button = event.target.closest("[data-error-id]");
      if (!button) return;
      const task = state.tasks.find((item) => item.id === Number(button.dataset.errorId));
      if (!task) return;
      $("#error-title").textContent = `任务 #${task.id} 的错误详情`;
      $("#error-body").textContent = task.error_message;
      $("#error-dialog").showModal();
    });
  }
  if (page === "prompts") {
    loadPrompts();
    $("#new-prompt").addEventListener("click", () => openPromptForm());
    $("#close-prompt-form").addEventListener("click", () => $("#prompt-form-card").hidden = true);
    $("#cancel-prompt").addEventListener("click", () => $("#prompt-form-card").hidden = true);
    $("#prompt-form").addEventListener("submit", savePrompt);
    $("#prompt-list").addEventListener("click", async (event) => {
      const button = event.target.closest("[data-prompt-action]");
      if (!button) return;
      const prompt = state.prompts.find((item) => item.id === Number(button.dataset.promptId));
      if (!prompt) return;
      if (button.dataset.promptAction === "view") {
        const body = $(`#prompt-body-${prompt.id}`);
        body.hidden = !body.hidden;
        button.textContent = body.hidden ? "查看" : "收起";
      } else if (button.dataset.promptAction === "copy") openPromptForm(prompt);
      else {
        button.disabled = true;
        try {
          await request(`${API}/prompts/${prompt.id}`, { method: "PATCH", body: JSON.stringify({ status: prompt.status === "ACTIVE" ? "INACTIVE" : "ACTIVE" }) });
          await loadPrompts();
          toast("模板状态已更新。");
        } catch (error) { button.disabled = false; toast(error.message, true); }
      }
    });
  }
}

setup();

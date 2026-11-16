# 贡献指南

感谢关注 PaperPulse！本文说明如何参与贡献。

## 项目概览

- **数据抓取**：`scripts/fetch.py`（Python，依赖 feedparser + requests）
- **数据源配置**：`config/sources.json`（RSS/Atom 源 + PubMed 期刊）
- **前端**：`index.html` / `style.css` / `app.js`（纯静态页面，无构建步骤）
- **自动化**：GitHub Actions —— `fetch.yml` 定时抓取文献并提交 `data/`，`deploy.yml` 部署到 GitHub Pages

## 本地运行

1. 准备 Python 3.11 或更高版本；
2. 安装依赖：`pip install -r requirements.txt`；
3. 手动抓取：`python scripts/fetch.py`（默认抓取最近 3 天，可用 `DAYS_BACK=2` 覆盖）；
4. 预览前端：由于浏览器对 `file://` 的限制，建议启动本地 HTTP 服务（如 `python -m http.server`）后访问 `index.html`。

## 修改与提交

- 提交信息遵循 Conventional Commits（`feat:` / `fix:` / `chore:` / `docs:` 等）；
- 只提交项目自身文件；`.venv/`、`.DS_Store`、`__pycache__/` 已由 `.gitignore` 忽略；
- 仓库中不保留开发方案、审阅报告、修复报告等过程性文档，此类内容请在 PR 描述或外部文档中说明。

## 数据源变更

- 编辑 `config/sources.json`：RSS 条目包含 `name` / `url` / `enabled` / `publisher` / `issn` 字段，Springer Nature 源额外使用 `springernature: true`；
- 新增或调整数据源后，运行一次 `python scripts/fetch.py` 验证输出，并确认 `data/index.json` 日期列表正确。

## 提交 PR

1. 从最新的 `main` 切出新分支；
2. 提交修改并推送分支；
3. 向 `main` 发起 Pull Request，等待 CI 与审查。

## 行为准则

请保持友善与尊重，专注于技术讨论。

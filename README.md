# PaperPulse

期刊文献日报，由 GitHub Actions 驱动，部署到 GitHub Pages。

## 架构

```
PaperPulse/
├── .github/workflows/
│   ├── fetch.yml       # 定时抓取文献，提交到 data/
│   └── deploy.yml      # 部署到 GitHub Pages
├── config/
│   └── sources.json    # 83 RSS 源 + 26 PubMed 期刊
├── scripts/
│   └── fetch.py        # 抓取、去重、输出 JSON
├── data/
│   ├── index.json      # 可用日期列表
│   └── YYYY-MM-DD.json # 每日文献数据
├── index.html          # 前端入口（三栏布局）
├── style.css           # 三栏样式
├── app.js              # 应用逻辑
├── requirements.txt
└── README.md
```

## 数据源

完全覆盖「期刊文献日报」的全部信息来源：

- **RSS/Atom feeds**: 83 个期刊（Nature, Science, Cell, PNAS, eLife, PLOS 等）
  - 含 Springer Nature API 路由（Science China Life/Earth Sciences, Microbiome, Genome Biology）
- **PubMed E-utilities**: 26 个期刊（ASM, Oxford, Royal Society 等）

## 前端布局

三栏式编辑排版界面：

```
┌─────────────────────────────────────────────┐
│                   Masthead                   │
├─────────────────────────────────────────────┤
│                   Search Bar                 │
├──────────┬─────────────────────┬────────────┤
│          │                     │            │
│ 左边栏    │   中间栏（紧凑列表）  │  右边栏     │
│ 期刊树    │   文献条目           │  文献详情   │
│          │                     │            │
│ 按出版商  │   类型 + 标题        │  标题       │
│ 分组折叠  │   + 元数据           │  作者/DOI   │
│          │                     │  摘要       │
└──────────┴─────────────────────┴────────────┘
```

- **左边栏**：期刊按出版商分组，可展开/折叠。点击期刊名筛选中间栏列表。整个边栏可收起（`[` 键或左上角按钮）
- **中间栏**：紧凑文献列表，每行显示类型标签、标题（两行截断）、期刊+作者+日期
- **右边栏**：点击文献后展示完整详情（标题、期刊、作者、DOI、PMID、摘要）。整个面板可收起（`]` 键或关闭按钮），关闭后右侧出现重开按钮

## 部署

1. Fork 或推送到 GitHub 仓库
2. Settings → Pages → Source: GitHub Actions
3. Actions 页面手动触发 `Fetch Papers` 工作流
4. 自动部署后访问 GitHub Pages URL

工作流每天北京时间 12:00 和 24:00 各运行一次（`cron: '0 4,16 * * *'`，UTC 04:00/16:00），每次抓取当日与昨天的文献。

`Fetch Papers` 提交数据后会自动触发 `Deploy to GitHub Pages` 重新部署（通过 `workflow_run`）。这是因为 GitHub Actions 使用 `GITHUB_TOKEN` 推送的提交不会触发 `push` 类工作流，只靠 `on: push` 会导致站点一直停留在首次部署的版本。

## 数据保留策略

只保留最近 7 天（`RETENTION_DAYS=7`）的文献数据，每次抓取完成后自动清理更早的日期文件。所有日期计算均按**北京时间（UTC+8）**，避免服务器 UTC 时区导致的日期偏差。

1. **删除旧数据文件**：清理 `data/` 下超过 7 天的 `YYYY-MM-DD.json`
2. **收缩日期索引**：`index.json` 的 `dates` 列表只保留最近 7 天，前端日期导航自动同步

## 键盘快捷键

| 键 | 功能 |
|----|------|
| `/` | 聚焦搜索框 |
| `[` | 切换左边栏 |
| `]` | 切换右边栏 |
| `Esc` | 关闭右边栏（未固定时） |

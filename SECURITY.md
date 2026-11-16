# 安全策略

## 支持的版本

| 版本 | 支持状态 |
| --- | --- |
| `main` 分支（最新） | ✅ 支持 |
| 历史提交 / 旧快照 | ❌ 不再接收安全更新 |

## 报告漏洞

- 请通过 GitHub 的私有漏洞报告功能（仓库 **Security** 标签页 → **Report a vulnerability**）提交；
- 也可新开 Issue 并在标题标注 `[Security]`，但请勿在公开 Issue 中披露可利用的细节；
- 重点关注方向：`scripts/fetch.py` 的依赖与输入处理、GitHub Actions 工作流权限、`data/` 数据注入风险。

## 安全实践

- 项目不收集任何用户数据，仓库与工作流中不保存任何凭据；
- 依赖通过 `requirements.txt` 声明最低版本，建议定期升级以获取安全修复；
- 工作流遵循最小权限原则（抓取任务仅 `contents: write`，部署任务使用 Pages 专用权限）。

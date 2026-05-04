# 🚀 OpenReview Agent

<p align="center">
  <strong>面向 OpenReview 投稿工作流的 Agent Skill 与 CLI 工具包。</strong>
</p>

<p align="center">
  • 投稿协作助手 • 跨会场转投 • 默认 Dry-run 的 OpenReview 自动化 •
</p>

<p align="center">
  <a href="README.md">English</a> •
  <a href="#-功能亮点">功能亮点</a> •
  <a href="#-快速开始">快速开始</a> •
  <a href="#-工作流">工作流</a> •
  <a href="#-安全模型">安全模型</a> •
  <a href="SKILL.md">Agent 指南</a> •
  <a href="SECURITY.md">安全说明</a>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
  <img alt="Status" src="https://img.shields.io/badge/status-0.1.0--alpha-orange">
  <img alt="OpenReview" src="https://img.shields.io/badge/OpenReview-ready-111827">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude%20Code-skill--ready-6b46c1">
  <img alt="Codex" src="https://img.shields.io/badge/Codex-skill--ready-111827">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-blue">
</p>

> [!IMPORTANT]
> **📚 从手工填表到 submission-native agents。**  
> OpenReview 工作流不只是一个提交按钮：作者需要对齐 venue schema、作者 profile ID、reviewer nomination、LLM usage 声明、dataset/code 链接、PDF/checklist 约束，以及不同会议的特殊政策。
>
> **🧭 默认 dry-run 的自动化。**  
> Agent 应该先帮助研究者 inspect、plan、validate 和 explain，再决定是否写入 OpenReview。
>
> **🔓 为什么开源？**  
> 很多 OpenReview 自动化都散落在私人脚本里。OpenReview Agent 提供一个可检查、可复现、默认安全的本地 skill 与 CLI 工具层。

## 🧭 快速导航

> [!TIP]
> **我是人类用户** -> 继续阅读本 README，了解安装、工作流、安全边界和项目定位。
>
> **我是 Agent** -> 阅读 [SKILL.md](SKILL.md)，里面有操作规则、状态码、命令契约和错误恢复模式。

`openreview-agent` 是一个 agent skill + CLI toolkit，用来帮助 AI agent 和研究者检查 OpenReview 投稿、基于单位证据匹配作者 profile、安全编辑 metadata、规划跨会场转投，并执行默认 dry-run 的批量投稿准备。

- **给作者**：减少 deadline 前作者 ID、venue 字段、附件、reviewer nomination 等低级错误。
- **给 Agent**：用结构化工具替代临时拼的一次性 Python 脚本。
- **给 OpenReview 安全性**：先 inspect，再生成 payload，最后只有在显式确认后才写入。

**状态：** `0.1.0-alpha`

> 本项目不隶属于 OpenReview、NeurIPS、ICLR、ICML、CVPR、ECCV 或任何会议组织。请只在你有权限访问和修改的账号、venue 与数据上使用。

## ⚡ 快速开始

```bash
git clone https://github.com/OpenClaudex/openreview-agent.git
cd openreview-agent
pip install -r requirements.txt
```

安装后，用自然语言指挥你的 coding agent 即可。例如：让它检查某个 OpenReview submission、根据单位证据匹配作者 profile、准备一次跨会场转投 dry-run，或在你明确确认后批量创建 submissions。

OpenReview 凭据可以通过 token、环境变量或交互式输入提供。底层命令细节放在 [SKILL.md](SKILL.md)，不放在 README 里。

## ✨ 功能亮点

OpenReview Agent 聚焦作者侧 OpenReview 工作流：

- 检查已有 forum note、签名、readers/writers、license、content keys 和可编辑 schema。
- 用作者姓名 + 单位/履历证据匹配 OpenReview profile。
- 抓取源 submission metadata，用于跨会场转投规划。
- 将源字段映射到目标 venue invitation schema，并检查 enum、长度、作者、匿名化和重复投稿风险。
- 写入前生成 dry-run payload。
- 只有在显式确认后才执行真实写入。
- 从 JSON / JSONL 批量创建独立 submissions，默认仍然是 dry-run-first。
- 默认不自作主张生成复杂 `readers`、`writers`、`nonreaders` 权限；权限应优先交给 venue process。

## 🧩 工作流

| 等级 | 工作流 | 预期行为 |
|---|---|---|
| Stable | 检查已有投稿 | 读取 metadata、authors、authorids、content keys、license 和可编辑 schema |
| Stable | 作者 profile 匹配 | 按姓名和单位证据排序候选 OpenReview profiles |
| Stable | 跨会场转投 preflight | 抓取源 note、规划字段映射、校验目标 schema、生成 dry-run payload |
| Stable | 安全写入 | 只有显式确认后才写入，并再次检查 OpenReview 保存状态 |
| Limited | 批量投稿 | JSON/JSONL 输入、附件处理、逐条错误提示，最终政策责任由用户承担 |
| Best-effort | 自定义 venue 表单 | schema fallback + 人工核对 |

## 🛡️ 安全模型

OpenReview Agent 把所有写操作都视为高风险操作。

- **默认 dry-run。** 转投和批量命令默认不写入。
- **基于 schema 写入。** 目标 invitation schema 决定哪些字段可以被写。
- **不静默猜作者。** 低置信度 profile 匹配需要人类确认。
- **不默认生成复杂权限。** 默认不自造 readers/writers/nonreaders。
- **不保存凭据。** token/password 不应进入日志、payload、截图或示例。
- **不生成 review，不做 spam。** 这不是自动审稿机器人，也不是批量滥投工具。

在私有 venue 或真实投稿上使用前，请先阅读 [SECURITY.md](SECURITY.md)。

## 🧪 为什么存在

OpenReview 很强大，但作者侧工作流非常脆弱。一个小 metadata 错误就可能导致作者归属错误、reviewer matching 异常、匿名性泄露、必填声明缺失，或者因为某个 venue-specific 字段变化而在 deadline 前失败。

OpenReview Agent 不是完整审稿系统。它是一个本地执行层，用来让投稿工作流更安全：inspect、plan、dry-run、apply、verify。

## 📚 文档

- [Agent 指南](SKILL.md)
- [安全策略](SECURITY.md)
- [发布检查清单](docs/release-checklist.md)
- Venue 模板：[`config/venues`](config/venues)
- CLI 工具：[`scripts/or_transfer.py`](scripts/or_transfer.py), [`scripts/or_batch.py`](scripts/or_batch.py)

## 🗺️ 路线图

- **v0.1**：inspect、profile-match、一键转投 dry-run/apply、批量投稿 dry-run/apply。
- **v0.2**：基于源 venue reviews、meta-review、decision 的 review-aware 转投体检。
- **v0.3**：按目标会场和领域做公开 review pattern 分析。
- **v0.4**：在人工确认下起草 resubmission summary of changes。

## 🌐 相关项目

OpenReview Agent 聚焦作者侧投稿工作流。相关项目：

- [OpenReview](https://openreview.net/) - 开放同行评审平台。
- [openreview-py](https://github.com/openreview/openreview-py) - OpenReview 官方 Python client。
- [openreview/openreview-mcp](https://github.com/openreview/openreview-mcp) - 面向 `openreview-py` 知识和 introspection 的 MCP server。
- [OpenCodice-Research/openreview-mcp](https://github.com/OpenCodice-Research/openreview-mcp) - 偏只读的 OpenReview MCP，覆盖 submissions、reviews、rebuttals 和 decisions。

## ⭐ Star History

<a href="https://star-history.com/#OpenClaudex/openreview-agent&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=OpenClaudex/openreview-agent&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=OpenClaudex/openreview-agent&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=OpenClaudex/openreview-agent&type=Date" />
  </picture>
</a>

## 📄 License

[MIT](LICENSE)

---

<p align="center">
  如果这个项目帮你避免了 OpenReview deadline 前的低级错误，欢迎给一个 ⭐ Star！
</p>

<p align="center">
  <a href="https://github.com/OpenClaudex/openreview-agent/issues">Report Issues</a> ·
  <a href="https://github.com/OpenClaudex/openreview-agent/issues/new?labels=enhancement">Feature Requests</a>
</p>

---
name: openreview-agent
description: "OpenReview 投稿/转投自动化技能。给定源 forum URL/id 和目标 venue id，自动拉取源论文的 metadata、作者、PDF，映射到目标会场的 submission schema，做字段校验、作者 profile 激活检查、匿名化提示，并在显式确认后通过官方 openreview-py API 提交。典型场景：ECCV 拒稿转 NeurIPS、ICLR 拒稿转 ICML、一稿要同时投 ARR 和 COLM 这类跨会场搬运。用户说 '把这篇从 X 转投到 Y / 转投 / resubmit / cross-venue' 时使用。"
---

# OpenReview 跨会场转投

把一篇已经在 OpenReview 某会场存在的论文（forum note），按目标会场的 submission invitation schema 重新打包并提交。只做 metadata 搬运和字段适配，不改写内容本身。

## 定位与边界

- 这是 **执行器 + 校验器**，不是写作/润色工具。
- 内容层面的修改（正文改写、响应上一轮 review、重新画图）不在此 skill 范围内，上游应该已经处理好。
- 本 skill 只做：拉源 forum → 读目标 invitation → 字段映射 → 作者 profile 预检 → 匿名化提示 → dry-run → 显式确认后真 submit。
- **真 submit 永远需要用户显式传 `--i-confirm`**，脚本不会在任何隐式路径下自动提交。
- 支持批量创建 submission，但默认 dry-run；真实批量写入必须显式传 `--apply --i-confirm-batch`。
- 跨会场转投一次只面向一个目标 venue；批量投稿面向多条独立 metadata 记录，不用于批量跨会场滥投。

## 快速判断

- 用户给了源 forum URL/id + 目标 venue id → 走完整四步：fetch → plan → dry-run → submit。
- 用户只想看"能不能投"→ 只跑 plan，输出字段映射预览和风险项。
- 用户还在修改论文内容 → 回去改完 PDF 再来，不要用这个 skill 当半成品的中转。
- 用户想一稿多投 → 明确告诉用户按会场逐个跑转投流程，不做一条命令多会场投递。
- 用户要批量创建多条独立投稿 → 使用 `scripts/or_batch.py`，默认 dry-run，真实写入必须 `--apply --i-confirm-batch`。

## 前置条件

- Python 3.9+。
- 依赖：`pip install --user openreview-py`（写 API 走 v2，内部用 `openreview.api.OpenReviewClient`）。
- 凭据优先通过 `OPENREVIEW_TOKEN`；没有 token 时使用 `OPENREVIEW_USERNAME` / `OPENREVIEW_PASSWORD`。
- 若在交互式终端运行且未设置环境变量，脚本会提示输入用户名和密码；密码使用 `getpass`，不会回显。
- 凭据只用于当前用户账号范围内的读写；脚本不会把凭据写入日志或 payload 文件，也不要把密码放进命令行参数。

## 核心风险与保护机制

这几条是硬性约束，实现时不得绕过：

1. **所有写操作必须经过 plan → dry-run → submit 三段，不得跳过**。
2. **submit 必须带 `--i-confirm`**；未带直接拒绝并提示"请先看 dry-run 输出"。
3. **作者 profile 预检**：所有 authorids 在目标会场必须能 `get_profile` 命中；任何一个查不到，plan 直接报 `AUTHOR_PROFILE_MISSING`，并列出需要手动激活/改 profile id 的人。
4. **字段 enum 校验**：keywords / primary_area 这类枚举字段，必须从目标 invitation 的 schema 读出合法值，对不上的做模糊匹配并让用户确认，绝不静默映射。
5. **字数上限校验**：title / abstract / TL;DR 超目标上限时，直接报错并中止，不自动截断。
6. **匿名化提示**：若目标会场要求双盲，脚本在 plan 阶段扫一次源 PDF 第一页是否含常见 affiliation 关键词，给出 `ANONYMITY_WARNING`，但不自动替换 PDF——换 PDF 是用户的责任。
7. **禁止静默重提**：若当前账号在目标 venue 已有在审投稿且 title 相似度 >0.85，plan 报 `POSSIBLE_DUPLICATE` 并中止。

## 返回状态约定

和 xhs-direct-post 对齐的状态前缀风格，便于上层 agent 识别：

- `FETCH_STATUS: OK` / `NOT_FOUND` / `NO_PERMISSION`
- `PLAN_STATUS: READY` / `AUTHOR_PROFILE_MISSING` / `FIELD_MISMATCH` / `LENGTH_EXCEEDED` / `ANONYMITY_WARNING` / `POSSIBLE_DUPLICATE`
- `DRY_RUN_STATUS: PAYLOAD_READY`
- `SUBMIT_STATUS: SUBMITTED` / `REJECTED_BY_API` / `REJECTED_MISSING_CONFIRM`
- `TRANSFER_STATUS: DRY_RUN_READY` / `REJECTED_MISSING_CONFIRM`
- `BATCH_STATUS: DRY_RUN_READY` / `DONE` / `REJECTED_MISSING_CONFIRM` / `NO_RECORDS`
- `NEW_FORUM_URL: https://openreview.net/forum?id=...`（submit 成功后返回）

## 常用命令

脚本位置：`~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py`

### 0. Inspect / profile-match（写前必做）

检查目标 note 和当前 invitation 允许编辑的字段：

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py inspect \
  --forum-id https://openreview.net/forum?id=ABC123
```

按姓名和单位匹配 OpenReview profile，输出候选、履历和置信分；低分或同名候选必须人工确认：

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py profile-match \
  --name "Rang Li" \
  --affiliation "Peking University"
```

### 1. Fetch 源论文

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py fetch \
  --source https://openreview.net/forum?id=ABC123 \
  --out-dir /tmp/or_transfer/
```

产出：`/tmp/or_transfer/source.json`（content + authors + 元数据）、`source.pdf`（若源可下载）。

### 2. Plan（最重要的一步）

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py plan \
  --source-file /tmp/or_transfer/source.json \
  --target-venue NeurIPS.cc/2026/Conference \
  --out-file /tmp/or_transfer/plan.json
```

输出内容：
- 字段映射表（source field → target field，哪些直接搬、哪些需要调整）
- authorids 的 profile 预检结果
- 字段长度告警
- 目标 invitation 中的必填字段与当前映射的匹配情况
- 匿名化检查结果
- 重复投稿检查结果

任何一项红灯都会让 `PLAN_STATUS` 不为 `READY`，后续步骤会被拒绝。

### 3. Dry-run

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py dry-run \
  --plan-file /tmp/or_transfer/plan.json \
  --out-file /tmp/or_transfer/payload.json
```

产出将要 POST 的完整 `post_note_edit` 请求体（content、invitation、signatures 全齐），用户可以在终端里肉眼对照 OpenReview 网页表单逐字段核对。不发任何请求。

### 4. Submit

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py submit \
  --payload-file /tmp/or_transfer/payload.json \
  --i-confirm
```

若成功，返回新的 `NEW_FORUM_URL`。**submit 后立即去 OpenReview 网页端核对一次**，这是 CFP 里所有坑（利益冲突声明、supplementary 上传、resubmission 声明）最容易露馅的时刻。

### 组合命令

懒得分四步时：

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py run \
  --source https://openreview.net/forum?id=ABC123 \
  --target-venue NeurIPS.cc/2026/Conference \
  --work-dir /tmp/or_transfer/
```

`run` 会自动依次跑 fetch → plan → dry-run，**但不会执行 submit**；submit 必须显式用单独命令并带 `--i-confirm`。

一键转投入口：

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_transfer.py transfer \
  --source https://openreview.net/forum?id=ABC123 \
  --target-venue NeurIPS.cc/2026/Conference \
  --work-dir /tmp/or_transfer/
```

`transfer` 默认也是 dry-run；真实写入必须额外传 `--apply --i-confirm`。

批量创建独立 submission：

```
python3 ~/.codebuddy/skills/openreview-transfer/scripts/or_batch.py \
  --input-file submissions.jsonl \
  --venue-id NeurIPS.cc/2026/Conference \
  --signature ~First_Last1 \
  --out-file /tmp/or_batch_payload.json
```

真实批量写入必须额外传 `--apply --i-confirm-batch`。

## 目标会场模板（可选）

有些会场有特殊字段（resubmission 声明、previous venue 字段、COI 列表字段名），通用映射搞不定。这时候在 `config/venues/<venue_id_slug>.json` 下放一份模板覆盖：

```
config/venues/neurips_2026.json
config/venues/acl_arr.json
```

模板里可以声明：
- 字段重命名映射（`source_field → target_field`）
- 额外必填字段的默认值或生成规则
- 需要从源论文派生的特殊字段（比如"这是 resubmission 声明：原 forum id = XXX"）

脚本在 plan 阶段会自动加载对应模板，找不到时用通用映射并打印提示。

## 权限策略

OpenReview 的 `readers` / `writers` / `nonreaders` 决定谁能读写 note。批量创建 submission 时，有些脚本会默认生成类似 `[venue_id] + authorids` 的权限列表；这就是“复杂权限默认生成”。本 skill 默认**不主动生成复杂权限**，而是让目标 invitation / OpenReview process 决定权限，避免双盲泄露、作者看不到稿件、或 chair/process 权限异常。只有在用户明确要求且 invitation schema 允许时，才考虑显式传 readers/writers。

## 常见问题与处理

- `AUTHOR_PROFILE_MISSING`：先去让对应合著者在 OpenReview 注册/激活账号；或者确认 profile id 拼写（`~Firstname_Lastname1` 格式）。不要用邮箱冒充 profile id。
- `FIELD_MISMATCH` on keywords/primary_area：打开目标 invitation 的 JSON schema 看合法 enum，手动在 plan 输出里改成合法值后重跑 dry-run。
- `LENGTH_EXCEEDED`：回去改论文内容或 abstract，再跑 fetch。
- `ANONYMITY_WARNING`：换一份匿名版 PDF 覆盖 `source.pdf`，然后重跑 plan。
- `POSSIBLE_DUPLICATE`：先确认你没在目标会场已经投过同名论文；确实是要重投请手动撤掉旧的再 submit。
- `REJECTED_BY_API`：把 API 返回的完整错误贴给用户，不要吞；80% 是 invitation readers/writers/signatures 配置和默认模板对不上。

## 开源路线（v0.1 → v0.3）

本 skill 的目标是先服务你自己跑通一次真实转投，然后抽象成可开源的工具。路线：

- **v0.1（本版本）** 支持 inspect、profile-match、一键转投 dry-run/apply、批量投稿 dry-run/apply。
- **v0.2** 加 review-aware 转投体检：读取源会场 reviews / meta-review / decision，识别硬伤和转投红灯。
- **v0.3** 加全网公开 review pattern 分析：按目标会场/领域总结常见拒稿理由和修改建议。
- **v0.4** 加 resubmission 声明自动生成（从上一轮 review 和本轮修改 diff 起草 summary of changes 草案）。

不做：多用户托管服务、代 submit 服务、批量跨会场投递、AI 自动写 review。

## 资源

- 核心脚本：`scripts/or_transfer.py`
- Venue 模板：`config/venues/*.json`
- 官方 SDK 参考：https://openreview-py.readthedocs.io/
- OpenReview API 文档：https://docs.openreview.net/
- 场景化 how-to：`docs/cross-venue-transfer.md`

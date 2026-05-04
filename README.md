# openreview-agent

OpenReview submission copilot for researchers: inspect submissions, match author profiles, edit metadata safely, plan cross-venue transfers, and batch-create submissions with dry-run-first safeguards.

## 为什么要这个工具

OpenReview 官方 SDK 支持读写，但作者侧缺少一个安全的 submission copilot。手动投稿/转投要重新填几十个字段、对齐 venue schema、检查每个合著者的 profile、适配匿名规则、避免误撞重复投稿——每一步都是机械劳动，又都不能出错。

本 skill 做六件事，其它都不做：
1. 从源 forum 拉 metadata + PDF。
2. 按目标会场 invitation schema 做字段映射 + 校验。
3. 预检所有作者 profile、字段 enum、字数上限、匿名化、重复投稿。
4. 一键转投：默认只生成 dry-run payload，只有 `--apply --i-confirm` 才写入。
5. 批量投稿：支持 JSON / JSONL 输入，默认 dry-run，只有 `--apply --i-confirm-batch` 才批量创建。
6. 写后回读关键字段，验证 OpenReview 实际保存结果。

不做的事（保持项目小而安全）：
- 不帮你写 / 润色论文。
- 不代替你点"最终 submit"以外的任何学术决策。
- 不自动生成 review。
- 不默认生成复杂 readers/writers/nonreaders 权限。

## 安装

```
pip install --user openreview-py pypdf
# Preferred:
export OPENREVIEW_TOKEN=...
# Or:
export OPENREVIEW_USERNAME=you@example.com
export OPENREVIEW_PASSWORD=...
```

## 快速开始

写入前先 inspect / profile-match：

```
python3 scripts/or_transfer.py inspect --forum-id https://openreview.net/forum?id=ABC123
python3 scripts/or_transfer.py profile-match --name "Rang Li" --affiliation "Peking University"
```

跨会场转投 dry-run：

```
python3 scripts/or_transfer.py run \
  --source https://openreview.net/forum?id=ABC123 \
  --target-venue NeurIPS.cc/2026/Conference \
  --work-dir /tmp/or_transfer/
```

`run` 会跑 fetch → plan → dry-run，**不会 submit**。如果要一键转投，用 `transfer`，默认仍然只 dry-run：

```
python3 scripts/or_transfer.py transfer \
  --source https://openreview.net/forum?id=ABC123 \
  --target-venue NeurIPS.cc/2026/Conference \
  --work-dir /tmp/or_transfer/
```

真写入必须显式加：

```
python3 scripts/or_transfer.py transfer \
  --source https://openreview.net/forum?id=ABC123 \
  --target-venue NeurIPS.cc/2026/Conference \
  --work-dir /tmp/or_transfer/ \
  --apply --i-confirm
```

也可以手动提交 dry-run 产物：

```
python3 scripts/or_transfer.py submit \
  --payload-file /tmp/or_transfer/payload.json \
  --i-confirm
```

批量投稿使用 `or_batch.py`，输入为 JSON list 或 JSONL；默认 dry-run：

```
python3 scripts/or_batch.py \
  --input-file submissions.jsonl \
  --venue-id NeurIPS.cc/2026/Conference \
  --signature ~First_Last1 \
  --out-file /tmp/or_batch_payload.json
```

真批量创建必须显式加：

```
python3 scripts/or_batch.py \
  --input-file submissions.jsonl \
  --venue-id NeurIPS.cc/2026/Conference \
  --signature ~First_Last1 \
  --apply --i-confirm-batch --await-process
```

## 状态码

见 `SKILL.md`。关键的几个：`PLAN_STATUS: READY` 才能继续；`SUBMIT_STATUS: SUBMITTED` 表示成功并返回新 `NEW_FORUM_URL`。

## 路线图

- v0.1：inspect / profile-match / 一键转投 dry-run / 安全 apply / 批量投稿 dry-run+apply。
- v0.2：review-aware 转投体检：读取源会场 reviews、meta-review、decision，并结合公开 review 样本判断是否适合转投。
- v0.3：全网 review pattern 分析：按目标会场/领域聚合公开 review，生成 target-venue 风险清单和 resubmission 修改建议。
- v0.4：resubmission 声明自动生成（summary of changes 草案），人工确认后再写入。

## License

MIT（开源时再落文件）。

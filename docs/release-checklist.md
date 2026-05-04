# Release Checklist

## v0.1 alpha scope

- [x] Inspect an existing OpenReview forum/note before edits.
- [x] Match author profiles with affiliation/history evidence.
- [x] Fetch source submission metadata.
- [x] Generate a cross-venue transfer plan from target invitation schema.
- [x] Generate dry-run payloads without writing.
- [x] Apply transfer only with `--apply --i-confirm` / `--i-confirm`.
- [x] Batch-create independent submissions from JSON/JSONL, dry-run by default.
- [x] Batch apply only with `--apply --i-confirm-batch`.
- [x] Support token auth and safe interactive password input.
- [x] Document permission policy and credential handling.

## Must not ship as default behavior

- [ ] No automatic multi-venue mass submission.
- [ ] No automatic review generation or posting.
- [ ] No silent author profile guessing.
- [ ] No default custom `readers` / `writers` / `nonreaders` generation.

## v0.2+

- Review-aware transfer preflight from source reviews / meta-review / decision.
- Public review pattern analysis by target venue and area.
- Resubmission summary-of-changes drafting with human approval.

# Security Policy

`openreview-transfer` can read and write real OpenReview submissions. Treat it as a high-trust local automation tool, not as a hosted submission service.

## Credential handling

- Prefer `OPENREVIEW_TOKEN` when available.
- If using username/password, pass them via `OPENREVIEW_USERNAME` and `OPENREVIEW_PASSWORD`, or interactive prompt.
- Do not put passwords or tokens in shell history, logs, issue reports, screenshots, or examples.
- The tool must not persist credentials to payload files, plans, logs, or browser snapshots.

## Safe defaults

- Transfer and batch commands are dry-run by default.
- Real writes require explicit confirmation flags:
  - transfer/apply: `--apply --i-confirm`
  - batch apply: `--apply --i-confirm-batch`
- The tool inspects the target invitation schema and only keeps fields accepted by that schema.
- The tool does not generate complex `readers`, `writers`, or `nonreaders` by default; venue processes should own permissions unless the user explicitly overrides them.

## Human responsibility

Users remain responsible for:

- Correct author identities and OpenReview profile IDs.
- Venue policies, dual-submission rules, reviewer nomination, acknowledgements, and LLM usage declarations.
- PDF anonymization, paper checklist, Croissant metadata, dataset/code availability, and supplementary material.
- Final review of dry-run payloads and OpenReview's saved state.

## Non-goals

This project should not be used to:

- Generate or submit reviews automatically.
- Spam venues with bulk submissions.
- Bypass venue policy or dual-submission restrictions.
- Impersonate authors or confirm acknowledgements without authorization.

## Reporting issues

When reporting bugs, include command output with credentials redacted. Do not include OpenReview passwords, tokens, private review text, unpublished PDFs, or private author emails unless all involved parties have consented.

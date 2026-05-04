#!/usr/bin/env python3
"""Safe OpenReview batch submission helper.

Default mode is dry-run. Real writes require both --apply and --i-confirm-batch.
Input is JSON list or JSONL, one object per submission. Fields not allowed by
submission invitation are dropped and reported.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from or_transfer import _extract_target_schema, _load_client, _wrap_value

META_FIELDS = {
    "submission_invitation",
    "signature",
    "signatures",
    "license",
    "readers",
    "writers",
    "nonreaders",
}
DEFAULT_ATTACHMENT_FIELDS = {"pdf", "supplementary_material", "croissant_file"}


def _load_records(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text().strip()
    if not text:
        return []
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        rows = []
        for idx, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"line {idx} is not a JSON object")
            rows.append(obj)
        return rows
    obj = json.loads(text)
    if not isinstance(obj, list):
        raise ValueError("JSON input must be a list of objects")
    if not all(isinstance(row, dict) for row in obj):
        raise ValueError("all JSON list items must be objects")
    return obj


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
        return [part.strip() for part in stripped.split(";") if part.strip()]
    return [str(value)]


def _invitation_id(row: Dict[str, Any], args: argparse.Namespace) -> str:
    inv = row.get("submission_invitation") or args.invitation_id
    if inv:
        return inv
    if args.venue_id:
        return f"{args.venue_id}/-/Submission"
    raise ValueError("missing submission_invitation; provide --venue-id or --invitation-id")


def _signatures(row: Dict[str, Any], args: argparse.Namespace) -> List[str]:
    sigs = _as_list(row.get("signatures") or row.get("signature") or args.signature)
    if not sigs:
        raise ValueError("missing signature/signatures; provide --signature")
    return sigs


def _prepare_content(
    row: Dict[str, Any],
    allowed_fields: Iterable[str],
    base_dir: Path,
    attachment_fields: set[str],
    client: Any,
    invitation_id: str,
    apply: bool,
) -> tuple[Dict[str, Any], List[str]]:
    allowed = set(allowed_fields)
    content: Dict[str, Any] = {}
    dropped: List[str] = []

    for key, value in row.items():
        if key in META_FIELDS:
            continue
        if key not in allowed:
            dropped.append(key)
            continue
        if key in attachment_fields and isinstance(value, str) and value and not value.startswith("/"):
            file_path = Path(value).expanduser()
            if not file_path.is_absolute():
                file_path = base_dir / file_path
            if not file_path.exists():
                raise FileNotFoundError(f"attachment not found for {key}: {file_path}")
            if apply:
                value = client.put_attachment(str(file_path), invitation_id, key)
            else:
                value = str(file_path)
        content[key] = _wrap_value(value)
    return content, dropped


def cmd_batch(args: argparse.Namespace) -> int:
    records = _load_records(Path(args.input_file).expanduser())
    if not records:
        print("BATCH_STATUS: NO_RECORDS")
        return 2

    apply = bool(args.apply)
    if apply and not args.i_confirm_batch:
        print("BATCH_STATUS: REJECTED_MISSING_CONFIRM")
        print("Refusing to write batch submissions without --i-confirm-batch.")
        return 4

    client = None if args.dry_run and not apply else _load_client(args)
    attachment_fields = set(args.attachment_fields.split(",")) if args.attachment_fields else DEFAULT_ATTACHMENT_FIELDS
    base_dir = Path(args.input_file).expanduser().parent
    payloads = []
    successes = 0
    failures = 0

    for idx, row in enumerate(records, 1):
        try:
            invitation_id = _invitation_id(row, args)
            if client is None:
                client_for_schema = _load_client(args)
            else:
                client_for_schema = client
            inv = client_for_schema.get_invitation(invitation_id)
            allowed = _extract_target_schema(inv).keys()
            content, dropped = _prepare_content(row, allowed, base_dir, attachment_fields, client_for_schema, invitation_id, apply)
            signatures = _signatures(row, args)
            payload = {
                "index": idx,
                "invitation": invitation_id,
                "signatures": signatures,
                "note": {"content": content, "license": row.get("license", args.license)},
                "dropped_fields": dropped,
            }

            if not apply:
                payloads.append(payload)
                successes += 1
                continue

            from openreview.api import Note

            note_kwargs = {"content": content}
            if row.get("license", args.license):
                note_kwargs["license"] = row.get("license", args.license)
            edit = client_for_schema.post_note_edit(
                invitation=invitation_id,
                signatures=signatures,
                note=Note(**note_kwargs),
                await_process=args.await_process,
            )
            print(f"[OK] {idx}: edit={getattr(edit, 'id', None)} title={row.get('title')}")
            successes += 1
        except Exception as exc:
            failures += 1
            print(f"[ERROR] {idx}: {exc}", file=sys.stderr)
            if args.stop_on_error:
                break

    if not apply:
        out = Path(args.out_file).expanduser() if args.out_file else None
        data = {"mode": "dry-run", "payloads": payloads}
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            print(f"BATCH_STATUS: DRY_RUN_READY\npayload_file: {out}")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("BATCH_STATUS: DRY_RUN_READY")
        return 0 if failures == 0 else 1

    print(f"BATCH_STATUS: DONE successes={successes} failures={failures}")
    return 0 if failures == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="or_batch", description=__doc__)
    p.add_argument("--baseurl", default="https://api2.openreview.net")
    p.add_argument("--token", help="OpenReview API token; defaults to OPENREVIEW_TOKEN")
    p.add_argument("--username", help="OpenReview username/email; defaults to OPENREVIEW_USERNAME")
    p.add_argument("--password", help="OpenReview password; defaults to OPENREVIEW_PASSWORD")
    p.add_argument("--input-file", required=True, help="JSON list or JSONL records")
    p.add_argument("--venue-id", help="Venue id, e.g. NeurIPS.cc/2026/Conference")
    p.add_argument("--invitation-id", help="Explicit submission invitation id")
    p.add_argument("--signature", help="Default signature, e.g. ~First_Last1")
    p.add_argument("--license", default="CC BY 4.0")
    p.add_argument("--attachment-fields", help="Comma-separated attachment fields; default pdf,supplementary_material,croissant_file")
    p.add_argument("--out-file", help="Where to write dry-run payload JSON")
    p.add_argument("--dry-run", action="store_true", default=True, help="Default: do not write")
    p.add_argument("--apply", action="store_true", help="Actually create submissions")
    p.add_argument("--i-confirm-batch", action="store_true", help="Required with --apply")
    p.add_argument("--await-process", action="store_true")
    p.add_argument("--stop-on-error", action="store_true")
    return cmd_batch(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())

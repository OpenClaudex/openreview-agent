#!/usr/bin/env python3
"""OpenReview cross-venue transfer tool.

Subcommands: fetch | plan | dry-run | submit | run

Design principles:
- Never submit without explicit --i-confirm on the submit subcommand.
- Plan is the hard gate: any red light blocks downstream steps.
- No silent enum mapping: ambiguous fields are reported, not guessed.
- Credentials via env vars or a private local ~/.openreview.env file.
"""

from __future__ import annotations

import argparse
import getpass
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs


# ---------------------------------------------------------------------------
# Client bootstrap
# ---------------------------------------------------------------------------

_ALLOWED_ENV_KEYS = {
    "OPENREVIEW_BASE_URL",
    "OPENREVIEW_TOKEN",
    "OPENREVIEW_USERNAME",
    "OPENREVIEW_PASSWORD",
}


def _load_local_env(path: Path = Path.home() / ".openreview.env") -> None:
    """Load private local OpenReview credentials without requiring shell source."""
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _ALLOWED_ENV_KEYS:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _arg_value(args: Optional[argparse.Namespace], name: str) -> Optional[str]:
    if args is None:
        return None
    return getattr(args, name, None)


def _load_client(args: Optional[argparse.Namespace] = None):
    _load_local_env()
    try:
        import openreview  # noqa: F401
        from openreview.api import OpenReviewClient
    except ImportError:
        sys.exit(
            "ERROR: openreview-py not installed.\n"
            "Run: pip install --user openreview-py"
        )

    baseurl = _arg_value(args, "baseurl") or os.environ.get("OPENREVIEW_BASE_URL", "https://api2.openreview.net")
    token = _arg_value(args, "token") or os.environ.get("OPENREVIEW_TOKEN")
    username = _arg_value(args, "username") or os.environ.get("OPENREVIEW_USERNAME")
    password = _arg_value(args, "password") or os.environ.get("OPENREVIEW_PASSWORD")
    if username and not password and sys.stdin.isatty():
        password = getpass.getpass("OpenReview password: ")

    try:
        if token:
            return OpenReviewClient(baseurl=baseurl, token=token)
        if username and password:
            return OpenReviewClient(baseurl=baseurl, username=username, password=password)
    except Exception as exc:  # pragma: no cover - network dependent
        sys.exit(f"ERROR: failed to authenticate with OpenReview: {exc}")

    sys.exit(
        "ERROR: OpenReview credentials required. Set OPENREVIEW_TOKEN or "
        "OPENREVIEW_USERNAME / OPENREVIEW_PASSWORD in env or ~/.openreview.env."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_forum_id(source: str) -> str:
    """Accept a forum URL or a raw forum/note id."""
    if source.startswith("http"):
        qs = parse_qs(urlparse(source).query)
        ids = qs.get("id")
        if ids:
            return ids[0]
    return source.strip()


def _unwrap_value(v: Any) -> Any:
    """OpenReview v2 wraps content values as {'value': X, 'readers': [...]}.

    Unwrap to just the value for display and mapping purposes; readers/writers
    metadata is dropped because downstream venues have their own readers rules.
    """
    if isinstance(v, dict) and "value" in v:
        return v["value"]
    return v


def _wrap_value(v: Any) -> Dict[str, Any]:
    return {"value": v}


def _unwrap_content(content: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _unwrap_value(v) for k, v in (content or {}).items()}


def _print_status(key: str, value: str) -> None:
    print(f"{key}: {value}")


# ---------------------------------------------------------------------------
# inspect / profile-match
# ---------------------------------------------------------------------------

def _profile_history(profile: Any, limit: int = 5) -> List[Dict[str, Any]]:
    content = getattr(profile, "content", {}) or {}
    rows: List[Dict[str, Any]] = []
    for item in (content.get("history") or [])[:limit]:
        institution = item.get("institution") or {}
        rows.append({
            "position": item.get("position"),
            "start": item.get("start"),
            "end": item.get("end"),
            "institution": institution.get("name"),
            "domain": institution.get("domain"),
            "department": institution.get("department"),
        })
    return rows


def _profile_fullnames(profile: Any) -> List[str]:
    content = getattr(profile, "content", {}) or {}
    return [n.get("fullname") for n in (content.get("names") or []) if n.get("fullname")]


def _score_profile(profile: Any, name: str, affiliation: Optional[str]) -> int:
    score = 0
    target_name = name.lower().strip()
    fullnames = [n.lower() for n in _profile_fullnames(profile)]
    if target_name in fullnames:
        score += 30
    elif any(target_name in n or n in target_name for n in fullnames):
        score += 10

    if affiliation:
        aff = affiliation.lower().replace("the ", "")
        history_text = json.dumps(_profile_history(profile, limit=10), ensure_ascii=False).lower().replace("the ", "")
        if aff in history_text:
            score += 50
        for token in re.split(r"[^a-z0-9]+", aff):
            if len(token) > 3 and token in history_text:
                score += 2
    return score


def cmd_inspect(args: argparse.Namespace) -> int:
    client = _load_client(args)
    forum_id = _parse_forum_id(args.forum_id)
    try:
        note = client.get_note(forum_id)
    except Exception as exc:
        _print_status("INSPECT_STATUS", "NOT_FOUND")
        print(f"error: {exc}")
        return 2

    invitation_id = args.invitation_id or ((note.invitations or [None])[0])
    allowed_fields: List[str] = []
    if invitation_id:
        try:
            inv = client.get_invitation(invitation_id)
            allowed_fields = sorted(_extract_target_schema(inv).keys())
        except Exception as exc:
            print(f"warn: cannot load invitation schema: {exc}", file=sys.stderr)

    content = _unwrap_content(note.content or {})
    report = {
        "id": note.id,
        "forum": getattr(note, "forum", None),
        "number": getattr(note, "number", None),
        "invitation": invitation_id,
        "title": content.get("title"),
        "authors": content.get("authors"),
        "authorids": content.get("authorids"),
        "content_keys": sorted(content.keys()),
        "allowed_content_fields": allowed_fields,
        "license": getattr(note, "license", None),
        "readers": getattr(note, "readers", None),
        "writers": getattr(note, "writers", None),
        "signatures": getattr(note, "signatures", None),
    }
    _print_status("INSPECT_STATUS", "OK")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_profile_match(args: argparse.Namespace) -> int:
    client = _load_client(args)
    try:
        profiles = client.search_profiles(term=args.name) or []
    except Exception as exc:
        _print_status("PROFILE_MATCH_STATUS", "FAILED")
        print(f"error: {exc}")
        return 2

    candidates = []
    for profile in profiles[: args.limit * 3]:
        candidates.append({
            "score": _score_profile(profile, args.name, args.affiliation),
            "id": getattr(profile, "id", None),
            "names": _profile_fullnames(profile),
            "history": _profile_history(profile),
        })
    candidates.sort(key=lambda row: row["score"], reverse=True)
    report = {
        "query": args.name,
        "affiliation": args.affiliation,
        "candidates": candidates[: args.limit],
        "note": "Low-score or same-name candidates should be confirmed by the author before writing authorids.",
    }
    _print_status("PROFILE_MATCH_STATUS", "OK")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0

# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def cmd_fetch(args: argparse.Namespace) -> int:
    client = _load_client(args)
    forum_id = _parse_forum_id(args.source)

    try:
        note = client.get_note(forum_id)
    except Exception as exc:
        _print_status("FETCH_STATUS", "NOT_FOUND")
        print(f"error: {exc}")
        return 2

    content = _unwrap_content(note.content or {})
    payload = {
        "forum_id": note.id,
        "invitations": note.invitations,
        "signatures": note.signatures,
        "readers": note.readers,
        "writers": note.writers,
        "content": content,
    }

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "source.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # Attempt to download PDF attachment if present.
    pdf_field = content.get("pdf")
    if isinstance(pdf_field, str) and pdf_field:
        try:
            data = client.get_attachment(note.id, "pdf")
            (out_dir / "source.pdf").write_bytes(data)
        except Exception as exc:
            print(f"warn: pdf fetch failed: {exc}", file=sys.stderr)

    _print_status("FETCH_STATUS", "OK")
    print(f"source_file: {out_path}")
    return 0


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

ANON_KEYWORDS = [
    "university", "institute", "laboratory", "corresponding author",
    "acknowledgment", "acknowledgement", "funded by", "grant no",
    "@gmail", "@outlook", "github.com/",
]


def _load_venue_template(venue_id: str, skill_root: Path) -> Dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "_", venue_id.lower()).strip("_")
    path = skill_root / "config" / "venues" / f"{slug}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as exc:
            print(f"warn: failed to load venue template {path}: {exc}", file=sys.stderr)
    return {}


def _find_submission_invitation(client, venue_id: str) -> Any:
    """Heuristically find the submission invitation for a venue."""
    candidates = [
        f"{venue_id}/-/Submission",
    ]
    last_exc = None
    for inv_id in candidates:
        try:
            return client.get_invitation(inv_id)
        except Exception as exc:
            last_exc = exc
            continue
    # Fall back to listing invitations and matching on suffix.
    try:
        invs = client.get_invitations(prefix=venue_id, limit=200)
    except Exception as exc:
        raise RuntimeError(f"cannot list invitations for {venue_id}: {exc}") from exc
    for inv in invs or []:
        if inv.id.endswith("/-/Submission") or inv.id.endswith("/Submission"):
            return inv
    raise RuntimeError(
        f"submission invitation not found for {venue_id}; last error: {last_exc}"
    )


def _extract_target_schema(inv: Any) -> Dict[str, Any]:
    """Pull out the note.content schema from a v2 invitation."""
    edit = getattr(inv, "edit", None) or {}
    if isinstance(edit, dict):
        note = edit.get("note", {})
        return (note or {}).get("content", {}) or {}
    return {}


def _field_constraints(field_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Summarise type/enum/maxLength from a v2 invitation field schema."""
    value = field_schema.get("value", {}) if isinstance(field_schema, dict) else {}
    param = value.get("param", {}) if isinstance(value, dict) else {}

    # v2 represents allowed values in two ways: "enum" for scalar, "items" for arrays.
    raw_enum = param.get("enum") or param.get("items")
    enum_values: Optional[List[Any]] = None
    if isinstance(raw_enum, list):
        enum_values = []
        for e in raw_enum:
            if isinstance(e, dict) and "value" in e:
                enum_values.append(e["value"])
            else:
                enum_values.append(e)

    return {
        "type": param.get("type"),
        "enum": enum_values,
        "maxLength": param.get("maxLength"),
        "minLength": param.get("minLength"),
        "optional": param.get("optional", False),
        "regex": param.get("regex"),
    }


def _check_length(value: Any, max_len: Optional[int]) -> bool:
    if max_len is None or value is None:
        return True
    if isinstance(value, str):
        return len(value) <= max_len
    if isinstance(value, list):
        return all(isinstance(x, str) and len(x) <= max_len for x in value)
    return True


def _fuzzy_enum_match(value: str, enum: List[str]) -> Optional[str]:
    hits = difflib.get_close_matches(value, enum, n=1, cutoff=0.75)
    return hits[0] if hits else None


def _check_authors(client, author_ids: List[str]) -> Tuple[List[str], List[str]]:
    ok: List[str] = []
    missing: List[str] = []
    for aid in author_ids or []:
        try:
            prof = client.get_profile(aid)
            if prof and getattr(prof, "id", None):
                ok.append(aid)
            else:
                missing.append(aid)
        except Exception:
            missing.append(aid)
    return ok, missing


def _check_anonymity(pdf_path: Path) -> List[str]:
    if not pdf_path.exists():
        return []
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return ["PYPDF_NOT_INSTALLED"]
    try:
        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            return []
        first = (reader.pages[0].extract_text() or "").lower()
    except Exception:
        return ["PDF_PARSE_FAILED"]
    hits = [kw for kw in ANON_KEYWORDS if kw in first]
    return hits


def _check_duplicate(client, target_venue: str, title: str) -> Optional[str]:
    if not title:
        return None
    try:
        notes = client.search_notes(term=title, group=target_venue, limit=10)
    except Exception:
        return None
    for n in notes or []:
        existing_title = _unwrap_value((n.content or {}).get("title"))
        if not isinstance(existing_title, str):
            continue
        ratio = difflib.SequenceMatcher(None, existing_title.lower(), title.lower()).ratio()
        if ratio > 0.85:
            return n.id
    return None


def cmd_plan(args: argparse.Namespace) -> int:
    client = _load_client(args)
    skill_root = Path(__file__).resolve().parent.parent

    src = json.loads(Path(args.source_file).read_text())
    src_content: Dict[str, Any] = src.get("content", {}) or {}

    template = _load_venue_template(args.target_venue, skill_root)
    rename_map: Dict[str, str] = template.get("rename_map", {})
    defaults: Dict[str, Any] = template.get("defaults", {})
    extras_from_source: Dict[str, str] = template.get("extras_from_source", {})

    # User-supplied overrides (highest priority): JSON file with {field: value}.
    overrides: Dict[str, Any] = {}
    if getattr(args, "overrides", None):
        overrides = json.loads(Path(args.overrides).read_text())

    try:
        inv = _find_submission_invitation(client, args.target_venue)
    except Exception as exc:
        _print_status("PLAN_STATUS", "FIELD_MISMATCH")
        print(f"error: {exc}")
        return 2

    target_schema = _extract_target_schema(inv)

    # Build initial mapping: rename then copy same-name fields that exist in target.
    mapped: Dict[str, Any] = {}
    mapping_trace: List[Dict[str, Any]] = []
    for src_key, src_val in src_content.items():
        tgt_key = rename_map.get(src_key, src_key)
        if tgt_key in target_schema:
            mapped[tgt_key] = src_val
            mapping_trace.append({"source": src_key, "target": tgt_key, "action": "copied"})
        else:
            mapping_trace.append({"source": src_key, "target": None, "action": "dropped_not_in_target"})

    # Apply defaults (don't overwrite).
    for k, v in defaults.items():
        if k not in mapped:
            mapped[k] = v
            mapping_trace.append({"source": f"<default>", "target": k, "action": "defaulted"})

    # Derive extras from source (e.g. previous_forum_id for resubmission declaration).
    for tgt_key, src_key in extras_from_source.items():
        if src_key == "__source_forum_id__":
            mapped[tgt_key] = src.get("forum_id")
        elif src_key in src_content:
            mapped[tgt_key] = src_content[src_key]

    # User overrides: highest priority, wins over everything above.
    for k, v in overrides.items():
        mapped[k] = v
        mapping_trace.append({"source": "<override>", "target": k, "action": "overridden"})

    # Validate each target field.
    field_reports: List[Dict[str, Any]] = []
    status_flags: List[str] = []
    for fname, fschema in target_schema.items():
        c = _field_constraints(fschema)
        val = mapped.get(fname)
        report: Dict[str, Any] = {"field": fname, "constraints": c, "present": val is not None}

        if val is None:
            if not c.get("optional"):
                report["issue"] = "MISSING_REQUIRED"
                if "FIELD_MISMATCH" not in status_flags:
                    status_flags.append("FIELD_MISMATCH")
            else:
                report["note"] = "missing_but_optional"
            field_reports.append(report)
            continue

        if c.get("enum"):
            enum_values = c["enum"]
            if isinstance(val, list):
                bad = [x for x in val if x not in enum_values]
                if bad:
                    suggestions = {x: _fuzzy_enum_match(x, [str(e) for e in enum_values]) for x in bad}
                    report["issue"] = "ENUM_MISMATCH"
                    report["bad_values"] = bad
                    report["suggestions"] = suggestions
                    if "FIELD_MISMATCH" not in status_flags:
                        status_flags.append("FIELD_MISMATCH")
            elif isinstance(val, (str, bool)):
                if val not in enum_values:
                    report["issue"] = "ENUM_MISMATCH"
                    report["suggestion"] = _fuzzy_enum_match(str(val), [str(e) for e in enum_values])
                    if "FIELD_MISMATCH" not in status_flags:
                        status_flags.append("FIELD_MISMATCH")

        if not _check_length(val, c.get("maxLength")):
            report["issue"] = "LENGTH_EXCEEDED"
            if "LENGTH_EXCEEDED" not in status_flags:
                status_flags.append("LENGTH_EXCEEDED")

        field_reports.append(report)

    # Author profile check.
    author_ids = mapped.get("authorids") or src_content.get("authorids") or []
    ok_authors, missing_authors = _check_authors(client, author_ids)
    if missing_authors:
        status_flags.append("AUTHOR_PROFILE_MISSING")

    # Anonymity check on local PDF if present.
    pdf_path = Path(args.source_file).parent / "source.pdf"
    anon_hits = _check_anonymity(pdf_path) if args.check_anonymity else []
    if anon_hits and anon_hits not in (["PYPDF_NOT_INSTALLED"], ["PDF_PARSE_FAILED"]):
        status_flags.append("ANONYMITY_WARNING")

    # Duplicate check.
    title = mapped.get("title")
    if isinstance(title, dict):
        title = title.get("value")
    dup_id = _check_duplicate(client, args.target_venue, title) if isinstance(title, str) else None
    if dup_id:
        status_flags.append("POSSIBLE_DUPLICATE")

    overall = "READY" if not status_flags else status_flags[0]

    plan = {
        "source_forum_id": src.get("forum_id"),
        "target_venue": args.target_venue,
        "target_invitation": inv.id,
        "mapping_trace": mapping_trace,
        "field_reports": field_reports,
        "authors": {"ok": ok_authors, "missing": missing_authors},
        "anonymity_hits": anon_hits,
        "possible_duplicate_id": dup_id,
        "mapped_content": mapped,
        "status_flags": status_flags,
        "status": overall,
    }

    out_path = Path(args.out_file).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))

    _print_status("PLAN_STATUS", overall)
    print(f"plan_file: {out_path}")
    if status_flags:
        print(f"flags: {status_flags}")
    return 0 if overall == "READY" else 3


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------

def cmd_dry_run(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan_file).read_text())
    if plan.get("status") != "READY":
        _print_status("DRY_RUN_STATUS", "BLOCKED_BY_PLAN")
        print(f"plan status: {plan.get('status')}; flags: {plan.get('status_flags')}")
        return 3

    mapped = plan["mapped_content"]
    wrapped_content = {k: _wrap_value(v) for k, v in mapped.items()}

    payload = {
        "invitation": plan["target_invitation"],
        "signatures": ["~"],  # must be replaced by real signature id at submit time
        "note": {
            "content": wrapped_content,
        },
        "_meta": {
            "source_forum_id": plan["source_forum_id"],
            "target_venue": plan["target_venue"],
        },
    }

    out_path = Path(args.out_file).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    _print_status("DRY_RUN_STATUS", "PAYLOAD_READY")
    print(f"payload_file: {out_path}")
    print("note: signatures placeholder '~' will be resolved at submit time from your profile.")
    return 0


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

def cmd_submit(args: argparse.Namespace) -> int:
    if not args.i_confirm:
        _print_status("SUBMIT_STATUS", "REJECTED_MISSING_CONFIRM")
        print("Refusing to submit without --i-confirm. Review the dry-run payload first.")
        return 4

    client = _load_client(args)
    payload = json.loads(Path(args.payload_file).read_text())

    # Resolve signature: use the user's tilde id from their profile.
    try:
        me = client.get_profile()
        signature = me.id
    except Exception as exc:
        _print_status("SUBMIT_STATUS", "REJECTED_BY_API")
        print(f"cannot resolve signature: {exc}")
        return 5

    try:
        from openreview.api import Note
    except ImportError:
        _print_status("SUBMIT_STATUS", "REJECTED_BY_API")
        print("openreview-py Note import failed")
        return 5

    try:
        result = client.post_note_edit(
            invitation=payload["invitation"],
            signatures=[signature],
            note=Note(content=payload["note"]["content"]),
        )
    except Exception as exc:
        _print_status("SUBMIT_STATUS", "REJECTED_BY_API")
        print(f"api error: {exc}")
        return 5

    new_forum_id = None
    try:
        # post_note_edit returns an Edit; the created note is inside.
        note_obj = getattr(result, "note", None)
        new_forum_id = getattr(note_obj, "forum", None) or getattr(note_obj, "id", None)
    except Exception:
        pass

    _print_status("SUBMIT_STATUS", "SUBMITTED")
    if new_forum_id:
        _print_status("NEW_FORUM_URL", f"https://openreview.net/forum?id={new_forum_id}")
    print("Open the forum URL above and verify manually. Some fields (supplementary, COI) may still need UI attention.")
    return 0


# ---------------------------------------------------------------------------
# run (fetch -> plan -> dry-run, never submit)
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    work = Path(args.work_dir).expanduser()
    work.mkdir(parents=True, exist_ok=True)

    fetch_args = argparse.Namespace(source=args.source, out_dir=str(work))
    rc = cmd_fetch(fetch_args)
    if rc != 0:
        return rc

    plan_args = argparse.Namespace(
        source_file=str(work / "source.json"),
        target_venue=args.target_venue,
        out_file=str(work / "plan.json"),
        check_anonymity=True,
    )
    rc = cmd_plan(plan_args)
    if rc != 0:
        return rc

    dry_args = argparse.Namespace(
        plan_file=str(work / "plan.json"),
        out_file=str(work / "payload.json"),
    )
    rc = cmd_dry_run(dry_args)
    if rc != 0:
        return rc

    print("\nAll three stages passed. To submit, run:")
    print(
        f"  python3 {__file__} submit "
        f"--payload-file {work / 'payload.json'} --i-confirm"
    )
    return 0


def cmd_transfer(args: argparse.Namespace) -> int:
    """One-command transfer wrapper: fetch -> plan -> dry-run -> optional submit."""
    work = Path(args.work_dir).expanduser()
    work.mkdir(parents=True, exist_ok=True)

    rc = cmd_fetch(argparse.Namespace(**vars(args), out_dir=str(work)))
    if rc != 0:
        return rc

    rc = cmd_plan(argparse.Namespace(
        **vars(args),
        source_file=str(work / "source.json"),
        out_file=str(work / "plan.json"),
        check_anonymity=True,
    ))
    if rc != 0:
        return rc

    rc = cmd_dry_run(argparse.Namespace(**vars(args), plan_file=str(work / "plan.json"), out_file=str(work / "payload.json")))
    if rc != 0:
        return rc

    if not args.apply:
        _print_status("TRANSFER_STATUS", "DRY_RUN_READY")
        print(f"payload_file: {work / 'payload.json'}")
        print("Pass --apply --i-confirm to write to OpenReview.")
        return 0

    if not args.i_confirm:
        _print_status("TRANSFER_STATUS", "REJECTED_MISSING_CONFIRM")
        print("Refusing to write without --i-confirm.")
        return 4

    return cmd_submit(argparse.Namespace(**vars(args), payload_file=str(work / "payload.json")))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(prog="or_transfer", description=__doc__)
    p.add_argument("--baseurl", default=os.environ.get("OPENREVIEW_BASE_URL", "https://api2.openreview.net"))
    p.add_argument("--token", help="OpenReview API token; defaults to OPENREVIEW_TOKEN")
    p.add_argument("--username", help="OpenReview username/email; defaults to OPENREVIEW_USERNAME")
    p.add_argument("--password", help="OpenReview password; defaults to OPENREVIEW_PASSWORD")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inspect", help="Inspect a forum/note and its editable schema")
    pi.add_argument("--forum-id", required=True, help="Forum URL or id")
    pi.add_argument("--invitation-id", help="Override edit invitation id")
    pi.set_defaults(func=cmd_inspect)

    pm = sub.add_parser("profile-match", help="Search author profiles with affiliation evidence")
    pm.add_argument("--name", required=True)
    pm.add_argument("--affiliation")
    pm.add_argument("--limit", type=int, default=10)
    pm.set_defaults(func=cmd_profile_match)

    pf = sub.add_parser("fetch", help="Fetch source forum metadata + PDF")
    pf.add_argument("--source", required=True, help="Forum URL or id")
    pf.add_argument("--out-dir", required=True)
    pf.set_defaults(func=cmd_fetch)

    pp = sub.add_parser("plan", help="Map source to target schema and validate")
    pp.add_argument("--source-file", required=True)
    pp.add_argument("--target-venue", required=True, help="e.g. NeurIPS.cc/2026/Conference")
    pp.add_argument("--out-file", required=True)
    pp.add_argument("--overrides", help="JSON file of {field: value} to override mapped content")
    pp.add_argument("--check-anonymity", action="store_true", default=True)
    pp.set_defaults(func=cmd_plan)

    pd = sub.add_parser("dry-run", help="Emit post_note_edit payload without sending")
    pd.add_argument("--plan-file", required=True)
    pd.add_argument("--out-file", required=True)
    pd.set_defaults(func=cmd_dry_run)

    ps = sub.add_parser("submit", help="Actually submit (requires --i-confirm)")
    ps.add_argument("--payload-file", required=True)
    ps.add_argument("--i-confirm", action="store_true")
    ps.set_defaults(func=cmd_submit)

    pr = sub.add_parser("run", help="fetch + plan + dry-run (no submit)")
    pr.add_argument("--source", required=True)
    pr.add_argument("--target-venue", required=True)
    pr.add_argument("--work-dir", required=True)
    pr.set_defaults(func=cmd_run)

    pt = sub.add_parser("transfer", help="one-command transfer: dry-run by default; apply only with --apply --i-confirm")
    pt.add_argument("--source", required=True)
    pt.add_argument("--target-venue", required=True)
    pt.add_argument("--work-dir", required=True)
    pt.add_argument("--overrides", help="JSON file of {field: value} to override mapped content")
    pt.add_argument("--apply", action="store_true", help="Actually write to OpenReview after dry-run")
    pt.add_argument("--i-confirm", action="store_true", help="Required with --apply")
    pt.set_defaults(func=cmd_transfer)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Public exchange contract. Kept identical to Terrarium's scripts/catalog_contract.py."""

import hashlib
import json
import re
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
FORMS = {
    "games": "games",
    "scenes-and-environments": "scenes",
    "films-and-videos": "videos",
    "tools-and-mini-apps": "tools",
    "visualizations": "visualizations",
    "wallpapers-and-desktop": "wallpapers",
}
FIELDS = frozenset(
    {
        "kind",
        "slug",
        "status",
        "title",
        "creator",
        "creator_key",
        "creator_account",
        "description",
        "description_zh",
        "category",
        "category_label",
        "category_label_zh",
        "form",
        "forms",
        "gameplay",
        "theme",
        "language",
        "section",
        "section_reason_key",
        "section_reason_en",
        "section_reason_zh",
        "tech",
        "tech_source",
        "source_url",
        "source_label",
        "original",
        "demo_url",
        "external_play",
        "license",
        "license_zh",
        "license_spdx",
        "license_open",
        "code_status",
        "redistribution_confirmed",
        "thumb",
        "thumb_source",
        "published",
        "added",
        "code_bytes",
        "media_bytes",
        "size_bytes",
        "total_bytes",
        "runnable",
        "runs_in_browser",
        "members",
        "provenance",
        "based_on",
        "download",
    }
)
REVIEW_FIELDS = FIELDS - {"kind", "slug", "status"}
URL_FIELDS = {"source_url", "original", "demo_url", "external_play", "creator_account"}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MISSING = object()


def dump(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def safe_url(value):
    if not isinstance(value, str) or not value:
        return ""
    try:
        parsed = urlsplit(value)
        if (
            len(value) > 2000
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or "\\" in value
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            return ""
        parsed.port
    except ValueError:
        return ""
    return value


def identity(row):
    kind, slug = row.get("kind"), row.get("slug")
    if (
        kind not in {"work", "collection"}
        or not isinstance(slug, str)
        or len(slug) > 160
        or not SLUG.fullmatch(slug)
    ):
        raise ValueError("invalid_catalog_identity")
    return kind, slug


def normalize(row):
    identity(row)
    result = {key: value for key, value in row.items() if key in FIELDS}
    result.setdefault("status", "active")
    if result["status"] not in {"active", "withdrawn"}:
        raise ValueError("invalid_catalog_status")
    if result["status"] == "withdrawn":
        return {key: result[key] for key in ("kind", "slug", "status")}
    for key in (
        "title",
        "creator",
        "description",
        "description_zh",
        "category",
        "source_url",
        "license_spdx",
    ):
        value = result.get(key)
        if value is None:
            result.pop(key, None)
        elif not isinstance(value, str) or len(value) > 10000:
            raise ValueError("invalid_catalog_text")
    if not result.get("title", "").strip():
        raise ValueError("catalog_title_required")
    if result.get("form") not in FORMS:
        raise ValueError("invalid_catalog_form")
    for key in URL_FIELDS:
        if not result.get(key):
            result.pop(key, None)
        elif not safe_url(result[key]):
            raise ValueError("invalid_catalog_url")
    if "members" in result:
        if not isinstance(result["members"], list) or len(result["members"]) > 10000:
            raise ValueError("invalid_collection_members")
        members = []
        for member in result["members"]:
            if isinstance(member, str) and SLUG.fullmatch(member):
                members.append(member)
            elif isinstance(member, dict):
                value = {
                    key: v
                    for key, v in member.items()
                    if key
                    in {
                        "id",
                        "title",
                        "description",
                        "description_zh",
                        "demo_url",
                        "source_url",
                        "thumb",
                        "work",
                    }
                }
                if value.get("work") is not None and (
                    not isinstance(value["work"], str) or not SLUG.fullmatch(value["work"])
                ):
                    raise ValueError("invalid_collection_member_work")
                if any(
                    value.get(key) and not safe_url(value[key])
                    for key in ("demo_url", "source_url")
                ):
                    raise ValueError("invalid_collection_member_url")
                members.append(value)
            else:
                raise ValueError("invalid_collection_members")
        result["members"] = members
    # Reject non-finite numbers at every nesting level, including unknown JSON containers.
    dump(result)
    return result


def indexed(rows):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("invalid_catalog_records")
    result = {}
    for row in rows:
        value = normalize(row)
        key = identity(value)
        if key in result:
            raise ValueError("duplicate_catalog_identity")
        result[key] = value
    return result


def jsonl(rows):
    values = indexed(rows)
    return "".join(dump(values[key]) + "\n" for key in sorted(values)).encode()


def parse_jsonl(payload):
    if len(payload) > 16 * 1024**2:
        raise ValueError("catalog_response_too_large")
    rows = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
    return list(indexed(rows).values())


def merge_record(base, local, remote):
    """Merge disjoint edits, retaining local values on conflicts or remote absence."""
    if remote is None:
        return local, []
    if local is None:
        return remote, []
    base = base or {}
    if remote.get("status") == "withdrawn" and local != base and local != remote:
        return local, ["status"]
    result = dict(local)
    conflicts = []
    for key in base.keys() | remote.keys():
        old, current, desired = (
            base.get(key, MISSING),
            local.get(key, MISSING),
            remote.get(key, MISSING),
        )
        if old == desired or current == desired:
            continue
        if current != old:
            conflicts.append(key)
        elif desired is MISSING:
            result.pop(key, None)
        else:
            result[key] = desired
    return result, sorted(conflicts)

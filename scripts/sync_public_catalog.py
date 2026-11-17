#!/usr/bin/env python3
"""Render the reviewed platform snapshot mirrored on HF, preserving GitHub-side edits."""

import argparse
import hashlib
import html
import json
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from catalog_contract import (
    FORMS,
    digest,
    dump,
    identity,
    indexed,
    jsonl,
    merge_record,
    parse_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]
REPO = "AI-Terrarium/terrarium-open-works"
FILES = (
    "catalog.jsonl",
    "catalog-sync.json",
    "metadata.jsonl",
    "catalog-creators.json",
    "catalog-tags.json",
    "catalog-metrics.json",
)


def fetch(url, missing=False):
    try:
        with urlopen(
            Request(url, headers={"User-Agent": "Terrarium-Catalog-Publisher/1.0"}), timeout=20
        ) as response:
            data = response.read(16 * 1024**2 + 1)
    except HTTPError as error:
        if missing and error.code == 404:
            return None
        raise
    if len(data) > 16 * 1024**2:
        raise ValueError("snapshot_too_large")
    return data


def download(wait_seconds=0, *, revision=None, batch_id=None):
    if revision is not None and not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("invalid_source_revision")
    deadline = time.monotonic() + wait_seconds
    now = datetime.now(timezone.utc)
    anchor = now.replace(hour=1, minute=0, second=0, microsecond=0)
    slot = anchor + (int((now - anchor) // timedelta(hours=8))) * timedelta(hours=8)
    while True:
        selected = revision
        if selected is None:
            info = json.loads(fetch(f"https://huggingface.co/api/datasets/{REPO}?expand[]=sha"))
            selected = info["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", selected):
            raise ValueError("invalid_source_revision")
        root = f"https://huggingface.co/datasets/{REPO}/raw/{selected}/"
        marker = fetch(root + "catalog-sync.json", missing=True)
        if marker is None:
            if batch_id:
                raise ValueError("expected_batch_missing")
            return None, selected
        manifest = json.loads(marker)
        if batch_id and manifest.get("batch_id") != batch_id:
            raise ValueError("source_batch_mismatch")
        generated = datetime.fromisoformat(manifest["generated_at"].replace("Z", "+00:00"))
        if revision or generated >= slot or time.monotonic() >= deadline:
            return {
                name: marker if name == "catalog-sync.json" else fetch(root + name)
                for name in FILES
            }, selected
        time.sleep(min(15, max(0, deadline - time.monotonic())))


def merge_catalog(base_rows, local_rows, incoming_rows, resolutions=()):
    base, local, incoming = indexed(base_rows), indexed(local_rows), indexed(incoming_rows)
    result, conflicts = {}, []
    decisions = {
        identity(row): row for row in resolutions if row.get("decision") == "keep_platform"
    }
    for key in sorted(base.keys() | local.keys() | incoming.keys()):
        own, desired = local.get(key), incoming.get(key)
        decision = decisions.get(key)
        if decision and own and digest(own) == decision.get("remote_hash"):
            if desired is None:
                continue
            own = dict(own)
            for field in decision.get("fields", []):
                if field in desired:
                    own[field] = desired[field]
                else:
                    own.pop(field, None)
        value, collision = merge_record(base.get(key), own, desired)
        if value is not None:
            result[key] = value
        if collision:
            conflicts.append({"kind": key[0], "slug": key[1], "fields": collision})
    return list(indexed(list(result.values())).values()), conflicts


def canonical_url(value):
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if parsed.hostname == "github.com":
        path = path.lower().removesuffix(".git")
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), path, parsed.query


def archive_matches(record, archive):
    """A shared slug alone cannot attach another author's archived source files."""
    creator = (record.get("creator") or "").strip().lstrip("@").casefold()
    owner = (archive.get("creator") or "").strip().lstrip("@").casefold()
    if creator and owner and creator != owner:
        return False
    source = canonical_url(record.get("source_url") or "")
    archived = canonical_url(archive.get("source_url") or "")
    return not (
        source[1] == archived[1] == "github.com" and source[2] != archived[2]
    )


def bootstrap_catalog(root, incoming_rows, archives):
    """Preserve the existing reviewed README entries when adding a structured feed."""
    from refresh_showcase import CARD, load_catalog, plain

    entries, catalog_date = load_catalog(root)
    incoming = indexed(incoming_rows)
    by_archive = {row["path"]: row for row in archives}
    by_url = {}
    for key, row in incoming.items():
        for field in ("original", "demo_url", "external_play", "source_url"):
            if row.get(field):
                by_url.setdefault((key[0], canonical_url(row[field])), set()).add(key)
    licenses = {}
    for category in FORMS.values():
        markup = (root / category / "README.md").read_text()
        for card in CARD.findall(markup):
            match = re.search(r'<b><a href="([^\"]+)">', card)
            sub = re.search(r"<sub>(.*?)</sub>", card, re.S)
            if match and sub:
                lines = [plain(v).split(" · ")[0].strip() for v in sub[1].split("<br>")[1:]]
                label = next(
                    (v for v in lines if v and not v.startswith("Collection of ")), "unknown"
                )
                licenses[html.unescape(match[1])] = label
        for row in re.findall(r"<tr><td>(.*?)</tr>", markup, re.S):
            cells = re.split(r"</td><td>", row)
            match = re.search(r'<a href="([^\"]+)">', cells[0])
            if len(cells) == 4 and match:
                licenses[html.unescape(match[1])] = plain(cells[2])
    result = {}
    reverse_form = {category: form for form, category in FORMS.items()}
    for ordinal, entry in enumerate(entries):
        kind = "collection" if entry.collection else "work"
        key = None
        if entry.files:
            path = urlsplit(entry.files).path.split("/tree/main/", 1)[-1]
            archive = by_archive.get(path)
            if archive:
                key = identity(archive)
        candidates = set()
        for url in (entry.url, entry.code):
            if url:
                candidates |= by_url.get((kind, canonical_url(url)), set())
        if key is None and len(candidates) == 1:
            key = next(iter(candidates))
        if key is None:
            exact = [
                candidate for candidate in candidates if incoming[candidate]["title"] == entry.title
            ]
            if len(exact) == 1:
                key = exact[0]
        if key is None:
            key = (kind, "github-" + digest([kind, entry.url, entry.title])[:24])
        if key in result:
            # Shared repository/demo links can represent distinct curated entries.
            # Retain a separate source identity for review instead of overwriting one.
            key = (
                kind,
                "github-" + digest([kind, entry.url, entry.title, entry.category, ordinal])[:24],
            )
        row = dict(
            incoming.get(
                key,
                {
                    "kind": kind,
                    "slug": key[1],
                    "form": reverse_form[entry.category],
                    "added": catalog_date,
                    "thumb": entry.thumbnail,
                    "members": [],
                }
                if kind == "collection"
                else {
                    "kind": kind,
                    "slug": key[1],
                    "form": reverse_form[entry.category],
                    "added": catalog_date,
                    "thumb": entry.thumbnail,
                },
            )
        )
        row.update(title=entry.title, creator=entry.creator, original=entry.url)
        if entry.code:
            row.update(source_url=entry.code)
            row.setdefault("code_status", "public")
        label = licenses.get(entry.url, "unknown")
        row["license_spdx"] = {
            "License unknown": "unknown",
            "All rights reserved": "LicenseRef-All-rights-reserved",
        }.get(label, label)
        result[key] = row
    return list(indexed(list(result.values())).values())


def apply_snapshot(root, bundle, revision):
    manifest = json.loads(bundle["catalog-sync.json"])
    if manifest.get("schema_version") != 1 or manifest.get("interval_hours") != 8:
        raise ValueError("unsupported_snapshot")
    incoming = parse_jsonl(bundle["catalog.jsonl"])
    if hashlib.sha256(bundle["catalog.jsonl"]).hexdigest() != manifest.get("catalog_sha256"):
        raise ValueError("snapshot_hash_mismatch")
    data = root / "data"
    local_path, base_path = data / "catalog.jsonl", data / "catalog-sync-baseline.jsonl"
    archives = [
        json.loads(line) for line in bundle["metadata.jsonl"].decode().splitlines() if line.strip()
    ]
    seen = set()
    for archive in archives:
        key = identity(archive)
        if (
            key in seen
            or archive.get("category") not in FORMS.values()
            or archive.get("path") != f"{archive['category']}/{archive['slug']}"
        ):
            raise ValueError("invalid_archive_index")
        seen.add(key)
    local = (
        parse_jsonl(local_path.read_bytes())
        if local_path.exists()
        else bootstrap_catalog(root, incoming, archives)
    )
    base = parse_jsonl(base_path.read_bytes()) if base_path.exists() else incoming
    merged, collisions = merge_catalog(base, local, incoming, manifest.get("resolutions", []))
    body = jsonl(merged)
    actual_hash = hashlib.sha256(body).hexdigest()
    active = [row for row in merged if row.get("status") != "withdrawn"]
    by_id = {identity(row): row for row in active}
    visible_archives = [
        row for row in archives
        if identity(row) in by_id and archive_matches(by_id[identity(row)], row)
    ]
    creators, tags = (
        json.loads(bundle["catalog-creators.json"]),
        json.loads(bundle["catalog-tags.json"]),
    )
    if not isinstance(creators, list) or not isinstance(tags, dict):
        raise ValueError("invalid_rendering_metadata")
    status = {
        "schema_version": 1,
        "source_batch_id": manifest["batch_id"],
        "source_hf_revision": revision,
        "catalog_sha256": actual_hash,
        "source_catalog_sha256": manifest["catalog_sha256"],
        "catalog_updated_at": manifest["catalog_updated_at"],
        "interval_hours": 8,
        "status": "ready" if actual_hash == manifest["catalog_sha256"] else "conflict",
        "conflicts": collisions,
    }
    # Validate the complete bundle before changing any generated catalog file.
    import sync_catalog

    original_root, original_argv = sync_catalog.ROOT, sys.argv
    try:
        with tempfile.TemporaryDirectory(prefix="terrarium-render-") as temporary:
            staging = Path(temporary)
            (staging / "thumbs").mkdir()
            (staging / "master.jsonl").write_bytes(jsonl(active))
            (staging / "works.json").write_text(
                dump([row for row in active if row["kind"] == "work"])
            )
            (staging / "collections.json").write_text(
                dump([row for row in active if row["kind"] == "collection"])
            )
            (staging / "metadata.jsonl").write_text(
                "".join(dump(row) + "\n" for row in visible_archives)
            )
            (staging / "creators.json").write_text(dump(creators))
            (staging / "tags.json").write_text(dump(tags))
            sync_catalog.ROOT = root
            sys.argv = [
                "sync_catalog.py",
                "--master",
                str(staging / "master.jsonl"),
                "--works",
                str(staging / "works.json"),
                "--collections",
                str(staging / "collections.json"),
                "--thumbs",
                str(staging / "thumbs"),
                "--metadata",
                str(staging / "metadata.jsonl"),
                "--creators",
                str(staging / "creators.json"),
                "--catalog-date",
                datetime.fromisoformat(manifest["catalog_updated_at"].replace("Z", "+00:00"))
                .astimezone(timezone(timedelta(hours=8)))
                .date()
                .isoformat(),
            ]
            sync_catalog.main()
    finally:
        sync_catalog.ROOT, sys.argv = original_root, original_argv
    data.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(body)
    base_path.write_bytes(jsonl(incoming))
    (data / "archive-index.jsonl").write_bytes(bundle["metadata.jsonl"])
    (data / "platform-metrics.json").write_bytes(bundle["catalog-metrics.json"])
    (data / "catalog-sync.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--hf-revision")
    parser.add_argument("--batch-id")
    parser.add_argument("--wait-seconds", type=int, choices=range(0, 601), default=0)
    args = parser.parse_args()
    if bool(args.hf_revision) != bool(args.batch_id) or (args.snapshot and args.hf_revision):
        parser.error("Pinned synchronization requires both --hf-revision and --batch-id")
    if args.snapshot:
        bundle, revision = (
            {name: (args.snapshot / name).read_bytes() for name in FILES},
            "offline-fixture",
        )
    else:
        bundle, revision = download(
            args.wait_seconds, revision=args.hf_revision, batch_id=args.batch_id
        )
    if bundle is None:
        print(json.dumps({"status": "source_not_ready", "source": REPO}))
        return
    print(json.dumps(apply_snapshot(args.root, bundle, revision), ensure_ascii=False))


if __name__ == "__main__":
    main()

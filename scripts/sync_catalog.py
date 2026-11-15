#!/usr/bin/env python3
"""Render the bilingual category source pages from the reviewed site catalog.

Example:
  python scripts/sync_catalog.py --master /path/catalog-snapshot.jsonl \
    --works /path/static/works.json --collections /path/static/collections.json \
    --thumbs /path/static/thumbs --metadata /path/hf/metadata.jsonl
"""

import argparse
from collections import defaultdict
from datetime import date
import html
import json
from pathlib import Path
import re
import shutil

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = "https://huggingface.co/datasets/awesome-fable-5-2/terrarium-open-works"
ORDER = ("games", "scenes", "videos", "tools", "visualizations", "wallpapers")
FORM_CATEGORY = {
    "games": "games", "scenes-and-environments": "scenes", "films-and-videos": "videos",
    "tools-and-mini-apps": "tools", "visualizations": "visualizations", "wallpapers-and-desktop": "wallpapers",
}
GAMEPLAY = (
    "shooter", "action-combat", "platformer", "racing-driving", "flight", "sports",
    "adventure-exploration", "puzzle", "strategy-management", "sandbox", "casual-arcade",
    "interactive-story", "simulation-visualization",
)
GAMEPLAY_TO_HEADING = dict(zip(GAMEPLAY, (
    "Shooter", "Action & combat", "Platformer & runner", "Racing & driving", "Flight", "Sports",
    "Adventure & exploration", "Puzzle", "Strategy & management", "Sandbox", "Casual & arcade",
    "Interactive story", "Simulation & visualization",
)))
GAMEPLAY_ANCHOR = dict(zip(GAMEPLAY, (
    "shooter", "action-and-combat", "platformer-and-runner", "racing-and-driving", "flight", "sports",
    "adventure-and-exploration", "puzzle", "strategy-and-management", "sandbox", "casual-and-arcade",
    "interactive-story", "simulation-and-visualization",
)))


def esc(value):
    return html.escape(" ".join(str(value or "").split()), quote=True)


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def entry_link(e):
    return e.get("original") or e.get("demo_url") or e.get("external_play") or e.get("source_url") or ""


def code_link(e, collection=False):
    status = e.get("code_status", "open" if collection and e.get("license_open") else "")
    url = e.get("source_url")
    if status in ("public", "open") and url:
        return url
    return ""


def license_text(e):
    value = e.get("license_spdx") or "unknown"
    if value == "unknown":
        return "License unknown"
    if value == "LicenseRef-All-rights-reserved":
        return "All rights reserved"
    return esc(value)


def render_card(e, category, files, thumb_names, creator_accounts, lang, collection=False):
    title, creator = esc(e.get("title")), esc(e.get("creator"))
    url = esc(entry_link(e))
    creator_url = esc(e.get("creator_account") or creator_accounts.get(e.get("creator_key"), ""))
    creator_markup = f'<a href="{creator_url}">{creator}</a>' if creator_url else creator
    code = code_link(e, collection)
    thumb = e.get("thumb", "")
    name = Path(thumb).name if thumb else ""
    description = e.get("description_zh") if lang == "zh-CN" else e.get("description", "")
    links = []
    if code:
        links.append(f'<a href="{esc(code)}">Code</a>')
    if files:
        path = files["path"].strip("/")
        links.append(f'<a href="{ARCHIVE}/tree/main/{esc(path)}">Files</a>')
    license = license_text(e)
    if name not in thumb_names:
        title_cell = f'<a href="{url}">{title}</a>'
        if collection:
            title_cell += f'<br>Collection of {len(e.get("members", []))} works'
        return "", f'<tr><td>{title_cell}</td><td>{creator_markup}</td><td>{license}</td><td>{" · ".join(links) or "—"}</td></tr>'

    parts = []
    if name in thumb_names:
        parts.append(f'<a href="{url}"><img src="../assets/thumbs/{esc(name)}" width="100%" alt="{title}" title="{esc(description)}"></a><br>')
    parts.append(f'<b><a href="{url}">{title}</a></b><br><sub>{creator_markup}<br>')
    if collection:
        parts.append(f'Collection of {len(e.get("members", []))} works<br>')
    parts.append(license)
    if links:
        parts.append(" · " + " · ".join(links))
    parts.append("</sub>")
    return f'<td width="25%" valign="top">{"".join(parts)}</td>', ""


def grid(cards, columns=4):
    rows = []
    for i in range(0, len(cards), columns):
        chunk = cards[i:i + columns]
        chunk += [f'<td width="{100 // columns}%"></td>'] * (columns - len(chunk))
        rows.append("<tr>\n" + "\n".join(chunk) + "\n</tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def render_category(category, entries, files, thumb_names, creator_accounts, tags, lang):
    out = []
    if category == "games":
        groups = defaultdict(list)
        for e in entries:
            tag = (e.get("gameplay") or e.get("gameplay_tags") or [None])[0]
            if isinstance(tag, list):
                tag = tag[0] if tag else None
            groups[tag if tag in GAMEPLAY else None].append(e)
        for key in (*GAMEPLAY, None):
            members = groups.get(key, [])
            if not members:
                continue
            if key is None:
                heading = "Other games" if lang == "en" else "其他游戏"
                anchor = "other-games"
            else:
                heading = GAMEPLAY_TO_HEADING[key]
                anchor = GAMEPLAY_ANCHOR[key]
                if lang == "zh-CN":
                    vocab = tags["vocabulary"]["gameplay"]
                    heading = vocab[key]["zh"]
            out.extend([f'<a name="genre-{anchor}"></a>', f'## {esc(heading)}', ""])
            cards, no_thumb = [], []
            for e in members:
                kind = e.get("kind", "work")
                card, row = render_card(e, category, files.get((kind, e["slug"])), thumb_names,
                                        creator_accounts, lang, kind == "collection")
                if card: cards.append(card)
                if row: no_thumb.append(row)
            out.append(grid(cards, 4))
            if no_thumb:
                label = "Works without a preview image:" if lang == "en" else "没有预览图的作品："
                out.extend(["", label, "", '<table>', '<tr><th align="left">Work</th><th align="left">Creator</th><th align="left">License</th><th align="left">Links</th></tr>', *no_thumb, '</table>'])
    else:
        cards, no_thumb = [], []
        for e in entries:
            kind = "collection" if e.get("kind") == "collection" else "work"
            card, row = render_card(e, category, files.get((kind, e["slug"])), thumb_names,
                                    creator_accounts, lang, kind == "collection")
            if card: cards.append(card)
            if row: no_thumb.append(row)
        out.append(grid(cards, 4))
        if no_thumb:
            label = "Works without a preview image:" if lang == "en" else "没有预览图的作品："
            out.extend(["", label, "", '<table>', '<tr><th align="left">Work</th><th align="left">Creator</th><th align="left">License</th><th align="left">Links</th></tr>', *no_thumb, '</table>'])
    return "\n\n".join(out)


def render_latest(records, files, thumb_names, creator_accounts, lang):
    eligible = []
    for kind, entry in records:
        name = Path(entry.get("thumb") or "").name
        if name not in thumb_names:
            continue
        published = entry.get("published") or entry.get("added") or ""
        added = entry.get("added") or ""
        eligible.append((published, added, kind, entry))
    eligible.sort(key=lambda row: (row[0], row[1], row[3]["slug"]), reverse=True)
    selected, creators = [], set()
    for row in eligible:
        creator_key = row[3].get("creator_key") or row[3].get("creator", "").casefold()
        if creator_key in creators:
            continue
        creators.add(creator_key)
        selected.append(row)
        if len(selected) == 8:
            break
    if len(selected) < 8:
        selected_ids = {(row[2], row[3]["slug"]) for row in selected}
        for row in eligible:
            if (row[2], row[3]["slug"]) not in selected_ids:
                selected.append(row)
                selected_ids.add((row[2], row[3]["slug"]))
                if len(selected) == 8:
                    break
    cards = []
    for _, _, kind, entry in selected:
        card, _ = render_card(entry, entry.get("category", ""), files.get((kind, entry["slug"])),
                              thumb_names, creator_accounts, lang, kind == "collection")
        # Homepage cards live at the repository root rather than in a category folder.
        cards.append(card.replace('src="../assets/', 'src="assets/'))
    return grid(cards, 4)


def validate_master(master, works, collections):
    expected = {(row["kind"], row["slug"]) for row in master}
    actual = {("work", row["slug"]) for row in works} | {("collection", row["slug"]) for row in collections}
    if len(expected) != len(master) or len(actual) != len(works) + len(collections):
        raise ValueError("master or static catalog contains duplicate kind/slug identities")
    if expected != actual:
        raise ValueError(f"master/catalog identity mismatch: missing={len(expected-actual)}, extra={len(actual-expected)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", required=True)
    parser.add_argument("--works", required=True)
    parser.add_argument("--collections", required=True)
    parser.add_argument("--thumbs", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--creators", required=True)
    args = parser.parse_args()
    master, works = read_jsonl(args.master), json.loads(Path(args.works).read_text())
    collections = json.loads(Path(args.collections).read_text())
    validate_master(master, works, collections)
    records = [("work", e) for e in works] + [("collection", e) for e in collections]
    by_id = {(kind, e["slug"]): e for kind, e in records}
    metadata = read_jsonl(args.metadata)
    files = {}
    for row in metadata:
        key = (row["kind"], row["slug"])
        expected_hf_category = FORM_CATEGORY.get(by_id[key].get("form")) if key in by_id else None
        if (key not in by_id or key in files or not row.get("category") or
                row.get("path") != f'{row["category"]}/{row["slug"]}' or
                row.get("category") != expected_hf_category):
            raise ValueError(f"invalid metadata identity/path: {key}")
        files[key] = row
    if len(files) != len(metadata):
        raise ValueError("archive metadata contains duplicate kind/slug identities")
    creators = json.loads(Path(args.creators).read_text())
    creator_accounts = {row["key"]: (row.get("account") or {}).get("url", "") for row in creators}
    static_thumbs = Path(args.thumbs)
    dest_thumbs = ROOT / "assets/thumbs"
    dest_thumbs.mkdir(parents=True, exist_ok=True)
    copied_thumbs = 0
    for kind, e in records:
        src = static_thumbs / Path(e.get("thumb") or "").name
        dest = dest_thumbs / src.name
        if e.get("thumb") and src.is_file() and not dest.is_file():
            with Image.open(src) as image:
                preview = ImageOps.fit(image.convert("RGB"), (400, 225), method=Image.Resampling.LANCZOS)
                preview.save(dest, "WEBP", quality=72, method=6)
            copied_thumbs += 1
    thumb_names = {p.name for p in dest_thumbs.glob("*.webp")}
    grouped = {cat: [] for cat in ORDER}
    for kind, e in records:
        category = FORM_CATEGORY.get(e.get("form"))
        if not category:
            raise ValueError(f"unknown form {e.get('form')} for {(kind, e['slug'])}")
        row = dict(e)
        row["kind"] = kind
        if kind == "collection":
            row["gameplay"] = []
        grouped[category].append(row)
    for category in ORDER:
        if category == "games":
            # Preserve reviewed source order within genre sections.
            pass
        else:
            grouped[category].sort(key=lambda e: (e["title"].casefold(), e["slug"]))
    tags = json.loads((static_thumbs.parent / "tags.json").read_text())
    stamp = max(row.get("added", "") for row in master)
    if not stamp:
        stamp = date.today().isoformat()
    for category in ORDER:
        entries = grouped[category]
        for lang in ("en", "zh-CN"):
            path = ROOT / category / f'README{"" if lang == "en" else ".zh-CN"}.md'
            old = path.read_text()
            start, end = "<!-- CATALOG:START -->", "<!-- CATALOG:END -->"
            head = old.split(start, 1)[0]
            tail = old.split(end, 1)[1]
            count = f"{len(entries)} entries." if lang == "en" else f"{len(entries)} 个条目。"
            head = re.sub(r'<p align="center">\d+ entries\..*?</p>|<p align="center">\d+ 个条目。.*?</p>',
                          f'<p align="center">{count}</p>', head, count=1, flags=re.S)
            body = render_category(category, entries, files, thumb_names, creator_accounts, tags, lang)
            path.write_text(head + start + "\n\n" + body + "\n\n" + end + tail)
    for lang, page in (("en", ROOT / "README.md"), ("zh-CN", ROOT / "docs/i18n/README.zh-CN.md")):
        profile = json.loads((ROOT / "scripts/locales.json").read_text())[lang]
        markup = page.read_text()
        start_marker = f'## {profile["nav"][1]}\n'
        before, rest = markup.split(start_marker, 1)
        # Keep the existing section heading, replacing only its cards.
        next_heading_at = markup.index("\n## ", markup.index(start_marker) + len(start_marker))
        latest_markup = render_latest(records, files, thumb_names, creator_accounts, lang)
        page.write_text(markup[:markup.index(start_marker) + len(start_marker)] + latest_markup + markup[next_heading_at:])
    # Keep generation dates in category pages aligned with the data snapshot.
    for category in ORDER:
        for suffix in ("", ".zh-CN"):
            path = ROOT / category / f"README{suffix}.md"
            path.write_text(re.sub(r"Catalog data: \d{4}-\d{2}-\d{2}", f"Catalog data: {stamp}", path.read_text()))
    print(f"Synced {len(records)} entries ({len(works)} works, {len(collections)} collections); {len(files)} Files links; added {copied_thumbs} thumbnails")


if __name__ == "__main__":
    main()

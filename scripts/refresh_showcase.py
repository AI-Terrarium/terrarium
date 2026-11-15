#!/usr/bin/env python3
"""Build the bilingual README showcase from the catalog and cross-platform engagement."""

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import html
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps

from heat import PLATFORM_NAMES, canonical_work_url, evidence_labels, fetch_metrics, rank_entries, source_for_url
from i18n import LOCALES, from_root, page_path, translate


ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("games", "videos", "scenes", "wallpapers", "tools", "visualizations")
START = "<!-- SHOWCASE:START -->"
END = "<!-- SHOWCASE:END -->"
CARD = re.compile(r'<td width="(?:25|33|33\.33|50)%" valign="top">(.*?)</td>', re.S)


@dataclass(frozen=True)
class Entry:
    title: str
    url: str
    creator: str
    category: str
    code: str = ""
    thumbnail: str = ""
    files: str = ""
    collection: bool = False
    social_urls: tuple = ()


def attach_engagement_links(root, entries):
    manifest = root / "data/engagement-links.json"
    if not manifest.is_file():
        return entries
    records = json.loads(manifest.read_text())["entries"]
    links = {canonical_work_url(record["work_url"]): tuple(record["posts"]) for record in records}
    known = {canonical_work_url(entry.url) for entry in entries}
    if set(links) - known:
        raise ValueError("Engagement manifest contains works not present in the catalog")
    for posts in links.values():
        if any(source_for_url(url) is None for url in posts):
            raise ValueError("Unsupported engagement source in manifest")
    return [replace(entry, social_urls=links.get(canonical_work_url(entry.url), ())) for entry in entries]

def plain(markup):
    return html.unescape(re.sub(r"<[^>]*>", "", markup)).strip()


def link_named(markup, label):
    match = re.search(r'<a href="([^"]+)">' + label + r"</a>", markup)
    return html.unescape(match[1]) if match else ""


def parse_entries(markup, category):
    """Read both preview cards and the catalog's tables without preview images."""
    entries = []
    for card in CARD.findall(markup):
        title = re.search(r'<b><a href="([^"]+)">(.*?)</a></b>', card, re.S)
        creator = re.search(r"<sub>(.*?)<br>", card, re.S)
        thumbnail = re.search(r'<img src="([^"]+)"', card)
        if not title or not creator:
            raise ValueError(f"Unrecognized preview card in {category}")
        entries.append(Entry(
            title=plain(title[2]), url=html.unescape(title[1]),
            creator=plain(creator[1]), category=category,
            code=link_named(card, "Code"), files=link_named(card, "Files"),
            thumbnail=f"assets/thumbs/{Path(thumbnail[1]).name}" if thumbnail else "",
            collection=bool(re.search(r"Collection of [\d,]+ works", card)),
        ))
    for row in re.findall(r"<tr><td>(.*?)</tr>", markup, re.S):
        cells = re.split(r"</td><td>", row)
        title = re.search(r'<a href="([^"]+)">(.*?)</a>', cells[0], re.S)
        if len(cells) != 4 or not title:
            raise ValueError(f"Unrecognized table row in {category}")
        entries.append(Entry(
            title=plain(title[2]), url=html.unescape(title[1]),
            creator=plain(cells[1]), category=category,
            code=link_named(cells[3], "Code"), files=link_named(cells[3], "Files"),
            collection=bool(re.search(r"Collection of [\d,]+ works", cells[0])),
        ))
    return entries


def load_catalog(root):
    entries, dates = [], []
    for category in CATEGORIES:
        markup = (root / category / "README.md").read_text()
        parsed = parse_entries(markup, category)
        expected = re.search(r'(\d+) entries\.', markup)
        if not expected or len(parsed) != int(expected[1]):
            raise ValueError(f"Entry count mismatch in {category}; check the catalog format")
        entries.extend(parsed)
        dates.append(re.search(r"(?:Data as of |Catalog data: )(\d{4}-\d{2}-\d{2})", markup)[1])
    # A heat refresh must never advance the date of the underlying catalog.
    return attach_engagement_links(root, entries), min(dates)


def recent_entries(root, entries):
    markup = (root / "README.md").read_text()
    heading = re.search(r"^## (?:Latest|Recently published)\s*$", markup, re.M)
    if heading is None:
        raise ValueError("README is missing its Latest section")
    recent = markup[heading.end():].split("\n## ", 1)[0]
    lookup = {(entry.title, entry.url): entry for entry in entries}
    return [lookup[(entry.title, entry.url)] for entry in parse_entries(recent, "recent")][:4]


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def select_entries(entries, recent, state):
    ranking = rank_entries(entries, state)
    if ranking:
        return [row[0] for row in ranking], True
    return recent, False


def ranking_lookup(entries, state):
    return {entry: (score, records) for entry, score, records in rank_entries(entries, state)}


def font(size, bold=False, content=""):
    cjk = any(0x2E80 <= ord(char) <= 0xFFFF for char in content)
    candidates = [os.environ.get("SHOWCASE_FONT", "")]
    if cjk:
        candidates.extend([
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ])
    candidates.extend([
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/System/Library/Fonts/Supplemental/Arial{' Bold' if bold else ''}.ttf",
    ])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def fit_lines(draw, content, face, width, limit=3):
    lines, line = [], ""
    for token in re.findall(r"\S+\s*", content):
        if draw.textlength(line + token.rstrip(), font=face) > width and line:
            lines.append(line.rstrip())
            line = ""
        # Long unspaced titles (including CJK) still wrap at character boundaries.
        while draw.textlength(token.rstrip(), font=face) > width:
            prefix = ""
            for char in token:
                if prefix and draw.textlength(prefix + char, font=face) > width:
                    break
                prefix += char
            lines.append(prefix.rstrip())
            token = token[len(prefix):]
        line += token
    if line:
        lines.append(line.rstrip())
    if len(lines) > limit:
        lines = lines[:limit]
        while draw.textlength(lines[-1] + "…", font=face) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def cached_preview(root, records):
    for record in records.values():
        if record.get("preview_url"):
            name = hashlib.sha256(record["preview_url"].encode()).hexdigest()[:16] + ".webp"
            path = root / "assets/showcase-previews" / name
            if path.is_file():
                return path
    return None


def cache_previews(root, entries, state):
    for entry, _, records in rank_entries(entries, state):
        if entry.thumbnail or cached_preview(root, records):
            continue
        for record in records.values():
            url = record.get("preview_url", "")
            host = urlsplit(url).hostname or ""
            if not (host.endswith(".hdslb.com") or host == "pbs.twimg.com"):
                continue
            try:
                with urlopen(Request(url, headers={"User-Agent": "Terrarium/1.0"}), timeout=20) as response:
                    payload = response.read(5_000_001)
                if len(payload) > 5_000_000:
                    continue
                with Image.open(BytesIO(payload)) as image:
                    preview = ImageOps.fit(image.convert("RGB"), (720, 330))
                    name = hashlib.sha256(url.encode()).hexdigest()[:16] + ".webp"
                    path = root / "assets/showcase-previews" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    preview.save(path, quality=88)
            except (OSError, ValueError):
                print(f"Preview unavailable: {entry.title}; using category placeholder", file=sys.stderr)


def render_banner(root, selected, ranked, state, catalog_date, now, ranking):
    frames = []
    lime, white, muted = "#c6f25a", "#eef0f3", "#9ba6b3"
    stale = bool(state["updated_at"] and now - parse_time(state["updated_at"]) > timedelta(hours=12))
    for index, entry in enumerate(selected):
        frame = Image.new("RGB", (1200, 450), "#0d1117")
        draw = ImageDraw.Draw(frame)
        draw.rounded_rectangle((24, 24, 36, 36), radius=3, fill=lime)
        label = "MOST LOVED IN TERRARIUM" if ranked else "NEW IN TERRARIUM"
        if ranked and stale:
            label = "MOST LOVED / LAST SNAPSHOT"
        draw.text((50, 19), label, font=font(20, True), fill=white)
        draw.text((864, 22), "WORLDS MADE WITH CODE", font=font(14), fill=muted)
        preview_path = root / entry.thumbnail if entry.thumbnail else cached_preview(root, ranking.get(entry, (0, {}))[1])
        if preview_path:
            with Image.open(preview_path) as preview:
                frame.paste(ImageOps.fit(preview.convert("RGB"), (720, 330)), (24, 66))
        else:
            draw.rounded_rectangle((24, 66, 744, 396), radius=12, fill="#1c2631")
            draw.text((80, 196), entry.category.upper(), font=font(42, True), fill=lime)
        x = 778
        draw.text((x, 70), f"{entry.category.upper()}  /  {index + 1:02d}", font=font(14, True), fill=lime)
        face = font(32, True, entry.title)
        for line_index, line in enumerate(fit_lines(draw, entry.title, face, 390)):
            draw.text((x, 108 + line_index * 41), line, font=face, fill=white)
        creator_face = font(16, content=entry.creator)
        creator = fit_lines(draw, "by " + entry.creator, creator_face, 390, limit=1)[0]
        draw.text((x, 242), creator, font=creator_face, fill=muted)
        if ranked:
            score, records = ranking[entry]
            record = next(iter(records.values()))
            preferred = "views" if record["platform"] in ("bilibili", "youtube") else "stars" if record["platform"] == "github" else "net_votes" if record["platform"] == "reddit" else "likes"
            primary = preferred if preferred in record["metrics"] else next(iter(record["metrics"]))
            count = record["metrics"][primary]
            number = f"{count / 1_000_000:.1f}M" if count >= 1_000_000 else f"{count:,}"
            draw.text((x, 284), number, font=font(44, True), fill=lime)
            label = f"{primary.replace('_', ' ').upper()} ON {PLATFORM_NAMES[record['platform']].upper()}"
            draw.text((x, 340), label, font=font(14, True), fill=muted)
            secondary = [f"{value:,} {key}" for key, value in record["metrics"].items() if key != primary and value > 0]
            line = " · ".join(secondary[:2]) or f"{score:,} public support interactions"
            draw.text((x, 373), line, font=font(16), fill=white)
        else:
            draw.text((x, 298), "PLAY. EXPLORE. BUILD.", font=font(23, True), fill=lime)
            draw.text((x, 339), "Discover our latest finds.", font=font(17), fill=white)
            draw.text((x, 374), "Recent releases / not a heat ranking", font=font(13), fill=muted)
        draw.text((24, 417), f"CATALOG  {catalog_date}", font=font(13), fill=muted)
        if ranked:
            stamp = parse_time(state["updated_at"]).strftime("%Y-%m-%d %H:%M UTC")
            footer = ("LAST SYNC  " if not stale else "STALE / LAST SYNC  ") + stamp
        else:
            footer = "HEAT RANKING PENDING" if not state["updated_at"] else "CROSS-PLATFORM DATA PENDING"
        draw.text((778, 419), footer, font=font(11), fill=muted)
        for dot in range(len(selected)):
            offset = 675 + dot * 19
            draw.ellipse((offset, 419, offset + 7, 426), fill=lime if dot == index else "#39424d")
        frames.append(frame)
    if not frames:
        raise ValueError("No entries available for the showcase")
    frames[0].save(root / "assets/showcase.webp", quality=88)
    frames[0].save(root / "assets/showcase.gif", save_all=True, append_images=frames[1:],
                   duration=3200, loop=0, disposal=2, optimize=True)


def showcase_markup(entries, selected, ranked, state, catalog_date, now, chinese=False, locale=None):
    code = locale or ("zh-CN" if chinese else "en")
    profile = LOCALES[code]
    ui = profile["ui"]
    ranking = ranking_lookup(entries, state)
    counts = [len(entries), len(CATEGORIES), sum(bool(e.code) for e in entries), sum(bool(e.files) for e in entries)]
    stamp = parse_time(state["updated_at"]).strftime("%Y-%m-%d %H:%M UTC") if state["updated_at"] else None
    stale = bool(stamp and now - parse_time(state["updated_at"]) > timedelta(hours=12))
    title = profile["nav"][0]
    status = translate(code, "synced", stamp=stamp) if stamp else ui["pending"]
    if stale:
        status += " · " + ui["stale"]
    if stamp and not ranked:
        status += " · " + ui["no_support"]
    catalog = translate(code, "catalog_date", date=catalog_date)
    stats = " · ".join(f"<b>{count}</b> {html.escape(label)}" for count, label in zip(counts, profile["stats"]))
    alt = f"Terrarium · {title}" if ranked else ui["pending"]
    lines = [START, f'<p align="center">{stats}<br><sub>{html.escape(catalog)}</sub></p>', "",
             '<a name="trending"></a>', "", f'## {title}', "",
             f'<p align="center"><a href="#showcase-links"><picture><source media="(prefers-reduced-motion: reduce)" srcset="assets/showcase.webp"><img src="assets/showcase.gif" width="100%" alt="{html.escape(alt, quote=True)}"></picture></a></p>', "",
             f'<p align="center"><sub>{html.escape(status)} · {html.escape(ui["cadence"])}</sub></p>', "",
             '<a name="showcase-links"></a>', "", '<table><tr>']
    for index, entry in enumerate(selected):
        url, name = html.escape(entry.url, quote=True), html.escape(entry.title)
        if ranked:
            _, records = ranking[entry]
            labels = evidence_labels(records, metric_names=profile["metrics"],
                                     prefix_labels=profile["metric_prefix"], separator=profile["separator"])
            details = "<br>".join(f'<a href="{html.escape(link, quote=True)}">{html.escape(label)}</a>' for link, label in labels)
        else:
            details = profile["nav"][1]
        lines.append(f'<td width="{100 // len(selected)}%" valign="top"><b>{index + 1:02d} · <a href="{url}">{name}</a></b><br><sub>{details}</sub></td>')
    lines.extend(['</tr></table>', ""])
    if ranked:
        coverage = translate(code, "coverage", sources=len(state["sources"]),
                             platforms=len({record["platform"] for record in state["sources"].values()}),
                             unavailable=len(state["unavailable"]))
        lines.extend([f'<details><summary>{html.escape(ui["sources_summary"])}</summary>', "",
                      f'{html.escape(profile["method"])} {html.escape(coverage)} <a href="data/showcase.json">{html.escape(ui["view_data"])}</a> · <a href="scripts/SHOWCASE.md">{html.escape(ui["methodology"])}</a>', "", '</details>', ""])
    lines.append(END)
    return from_root("\n".join(lines), code)


def replace_showcase(markup, block):
    if markup.count(START) != 1 or markup.count(END) != 1:
        raise ValueError("README must contain exactly one SHOWCASE marker pair")
    before, rest = markup.split(START)
    _, after = rest.split(END)
    return before + block + after


def build(root, state, now):
    entries, catalog_date = load_catalog(root)
    selected, ranked = select_entries(entries, recent_entries(root, entries), state)
    outputs = {}
    for code, profile in LOCALES.items():
        name = page_path(code)
        if not (root / name).is_file():
            continue
        block = showcase_markup(entries, selected, ranked, state, catalog_date, now, locale=code)
        outputs[name] = replace_showcase((root / name).read_text(), block)
    render_banner(root, selected, ranked, state, catalog_date, now, ranking_lookup(entries, state))
    for name, markup in outputs.items():
        (root / name).write_text(markup)
    return len(entries), len(state["sources"]), ranked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Fetch public cross-platform engagement before rendering")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    state_path = ROOT / "data/showcase.json"
    if args.refresh:
        entries, _ = load_catalog(ROOT)
        state = fetch_metrics(entries, now)
        cache_previews(ROOT, entries, state)
    else:
        state = json.loads(state_path.read_text())
    count, measured, ranked = build(ROOT, state, now)
    if args.refresh:
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    print(f"Built multilingual showcase: {count} entries, {measured} measured sources, "
          f"{'public-support ranking' if ranked else 'recent-release fallback'}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as error:
        print(f"Showcase refresh failed: {error}", file=sys.stderr)
        sys.exit(1)

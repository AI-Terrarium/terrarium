#!/usr/bin/env python3
"""Build localized homepages and category navigation from the reviewed catalog."""

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from urllib.parse import quote

from i18n import CONTENT_ORDER, GENRE_SLUGS, ICONS, LOCALES, from_root, language_bar, localize_markup, page_path, relative_link, translate
from refresh_showcase import CARD, ROOT, load_catalog, parse_entries, recent_entries, select_entries, showcase_markup

WEBSITE = "https://dbiewzjg1b9r0.cloudfront.net/index.html?license=yes"
ARCHIVE = "https://huggingface.co/datasets/awesome-fable-5-2/terrarium-open-works"
CAT_START, CAT_END = "<!-- CATALOG:START -->", "<!-- CATALOG:END -->"
FEATURED = {
    "games": ["orb-shooter-fps-demo-vibe-coded", "bumblebee-echo-garden", "pelican-ride"],
    "scenes": ["emberfall-forge", "oil-paint", "tiny-planet"],
    "videos": ["path-traced-voxel-creature", "the-edge", "colossus"],
    "tools": ["mgco2-v6-compression-engine-interactive-3d-viewer", "hourglass-digital-twin", "fiat-ludus"],
    "visualizations": ["entomia-3d-micro-morphology", "3d-sorting-algorithm-visualizer", "cube-physics-simulation"],
    "wallpapers": ["claude-pet", "c-vibe-screensaver"],
}


def esc(value):
    return html.escape(str(value), quote=True)


def header(code, category=None):
    p = LOCALES[code]
    current = page_path(code, category)
    logo = relative_link(current, 'assets/logo.svg')
    size = 64 if category else 92
    parts = ['<a name="top"></a>', f'<p align="center"><a href="{WEBSITE}"><img src="{logo}" width="{size}" height="{size}" alt="Terrarium"></a></p>']
    parts.append('<p align="center"><b>Terrarium</b></p>' if category else '<h1 align="center">Terrarium</h1>')
    if not category:
        parts.append(f'<p align="center"><b>{esc(p["tagline"])}</b></p>')
    badges = []
    for label, value, url in ((p["ui"]["website"], "Terrarium", WEBSITE), (p["ui"]["archive"], "Hugging Face", ARCHIVE)):
        image = f'https://img.shields.io/badge/{quote(label, safe="")}-{quote(value, safe="")}-c6f25a?labelColor=30363d'
        badges.append(f'<a href="{url}"><img src="{image}" height="22" alt="{esc(label)}"></a>')
    parts.append('<p align="center">' + "\n".join(badges) + '</p>')
    parts.append(language_bar(code, category))
    home = relative_link(current, page_path(code)) if category else ""
    parts.append('<p align="center">' + " · ".join(f'<a href="{home}#{anchor}">{esc(label)}</a>' for anchor, label in zip(("trending", "latest", "contents"), p["nav"])) + '</p>')
    return "\n\n".join(parts)


def footer(code, date, category=False):
    current = page_path(code, category if category else None)
    p = LOCALES[code]
    home = relative_link(current, page_path(code))
    logo = relative_link(current, 'assets/logo.svg')
    links = [f'<a href="{home}">{esc(p["ui"]["home"])}</a>']
    links.extend(f'<a href="{relative_link(current, page_path(code, cat))}">{esc(p["categories"][cat])}</a>' for cat in CONTENT_ORDER)
    links.append(f'<a href="#top">{esc(p["ui"]["back_top"])}</a>')
    return '\n\n---\n\n' + f'<p align="center"><a href="{home}"><img src="{logo}" height="32" alt="Terrarium"></a><br><sub>' + " · ".join(links) + '<br>' + esc(translate(code, "catalog_date", date=date)) + '</sub></p>\n'


def catalog_body(markup):
    if CAT_START in markup:
        return markup.split(CAT_START, 1)[1].split(CAT_END, 1)[0].strip()
    after_title = markup.index('</h1>') + len('</h1>')
    match = re.search(r'^## |^<table>', markup[after_title:], re.M)
    if match is None:
        raise ValueError("No category catalog body found")
    return markup[after_title + match.start():].split('\n---\n', 1)[0].strip()


def section_body(body, code, category):
    body = re.sub(r'<a name="genre-[^"]+"></a>\s*', '', body)
    if category == "games":
        index = 0
        def heading(_):
            nonlocal index
            result = f'<a name="genre-{GENRE_SLUGS[index]}"></a>\n\n## {LOCALES[code]["genres"][index]}'
            index += 1
            return result
        body = re.sub(r'^## .+$', heading, body, flags=re.M)
        if index != len(GENRE_SLUGS):
            raise ValueError("Game genres need translation updates")
    return localize_markup(body, code)


def cards_table(cards, code, columns=3):
    result = ['<table>']
    width = {2: '50', 3: '33.33', 4: '25'}[columns]
    for start in range(0, len(cards), columns):
        result.append('<tr>')
        for card in cards[start:start + columns]:
            card = re.sub(r'src="(?:\.\./)*assets/', 'src="assets/', card)
            result.append(f'<td width="{width}%" valign="top">{localize_markup(card, code)}</td>')
        for _ in range(columns - len(cards[start:start + columns])):
            result.append(f'<td width="{width}%"></td>')
        result.append('</tr>')
    result.append('</table>')
    return "\n".join(result)


def genre_nav(code, counts, target=""):
    return '<p>' + " · ".join(f'<a href="{target}#genre-{slug}">{esc(label)}</a> <b>{count}</b>' for slug, label, count in zip(GENRE_SLUGS, LOCALES[code]["genres"], counts)) + '</p>'


def contents(code, entries, bodies, genre_counts):
    p = LOCALES[code]
    parts = ['<a name="contents"></a>', '<a name="categories"></a>', f'## {p["nav"][2]}', esc(p["ui"]["contents_intro"]), '<table>']
    for offset in range(0, len(CONTENT_ORDER), 3):
        parts.append('<tr>')
        for cat in CONTENT_ORDER[offset:offset + 3]:
            group = [e for e in entries if e.category == cat]
            counts = f'{sum(bool(e.code) for e in group)} {p["stats"][2]} · {sum(bool(e.files) for e in group)} {p["stats"][3]}'
            parts.append(f'<td width="33.33%"><b><a href="#contents-{cat}">{ICONS[cat]} {esc(p["categories"][cat])}</a> · {len(group)}</b><br><sub>{esc(counts)}</sub></td>')
        parts.append('</tr>')
    parts.append('</table>')
    for cat in CONTENT_ORDER:
        count = sum(e.category == cat for e in entries)
        parts.extend([f'<a name="contents-{cat}"></a>', f'### {ICONS[cat]} {p["categories"][cat]} · {count}', esc(p["descriptions"][cat])])
        if cat == 'games':
            parts.append(genre_nav(code, genre_counts, f'games/{p["filename"]}'))
        source_code = code if code in ('en', 'zh-CN') else 'en'
        raw = CARD.findall(bodies[source_code][cat])
        by_slug = {Path(re.search(r'<img src="([^"]+)"', card)[1]).stem: card for card in raw}
        chosen = []
        for slug in FEATURED[cat]:
            if slug in by_slug:
                chosen.append(by_slug[slug])
        if len(chosen) < min(3, len(raw)):
            chosen.extend(card for card in raw if card not in chosen)
        parts.append(cards_table(chosen[:3], code, columns=min(3, len(chosen))))
        parts.append(f'<p><b><a href="{cat}/{p["filename"]}">{esc(translate(code, "browse_all", count=count))}</a></b> · <a href="#contents">↑ {esc(p["nav"][2])}</a></p>')
    return "\n\n".join(parts)


def build_all(root=ROOT):
    entries, date = load_catalog(root)
    state = json.loads((root / 'data/showcase.json').read_text())
    now = datetime.now(timezone.utc)
    selected, ranked = select_entries(entries, recent_entries(root, entries), state)
    bodies, latest = {}, {}
    for code in ('en', 'zh-CN'):
        p = LOCALES[code]
        bodies[code] = {cat: catalog_body((root / cat / p['filename']).read_text()) for cat in CONTENT_ORDER}
        home = (root / page_path(code)).read_text()
        latest_section = home.split(f'## {p["nav"][1]}\n', 1)[1].split('\n## ', 1)[0]
        latest[code] = CARD.findall(latest_section)
        if len(latest[code]) < 4:
            raise ValueError('Latest must include at least four reviewed preview cards')
    chunks = re.split(r'^## .+$', bodies['en']['games'], flags=re.M)[1:]
    genre_counts = [len(parse_entries(chunk, 'games')) for chunk in chunks]
    outputs = {}
    for code, p in LOCALES.items():
        source = code if code in ('en', 'zh-CN') else 'en'
        about = '\n\n'.join([f'<details><summary>{esc(p["ui"]["about_summary"])}</summary>', esc(p['about'][0]), esc(p['about'][1]), f'```sh\ngit clone {ARCHIVE}\n```', esc(p['about'][2]), f'<a href="scripts/SHOWCASE.md">{esc(p["ui"]["methodology"])}</a> · <a href="https://github.com/AI-Terrarium/terrarium/issues/new">{esc(p["ui"]["contribute"])}</a>', '</details>'])
        blocks = [header(code), showcase_markup(entries, selected, ranked, state, date, now, locale=code), '<a name="latest"></a>', f'## {p["nav"][1]}', from_root(cards_table(latest[source], code, columns=4), code), from_root(contents(code, entries, bodies, genre_counts), code), f'<p align="center"><a href="{WEBSITE}">{esc(p["ui"]["open_website"])}</a> · <a href="{ARCHIVE}">{esc(p["ui"]["get_code"])}</a></p>', from_root(about, code)]
        outputs[root / page_path(code)] = '\n\n'.join(blocks) + footer(code, date)
        for cat in CONTENT_ORDER:
            group = [e for e in entries if e.category == cat]
            introduction = translate(code, 'entry_count', count=len(group)) + ' ' + p['descriptions'][cat]
            nav = genre_nav(code, genre_counts) if cat == 'games' else ''
            body = section_body(bodies[source][cat], code, cat)
            outputs[root / cat / p['filename']] = '\n\n'.join([header(code, cat), f'<h1 align="center">{esc(p["categories"][cat])}</h1>', f'<p align="center">{esc(introduction)}</p>', nav, CAT_START, body, CAT_END]) + footer(code, date, cat)
    for path, value in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    print(f'Built {len(LOCALES)} homepages and {len(LOCALES) * len(CONTENT_ORDER)} category pages')


if __name__ == '__main__':
    build_all()

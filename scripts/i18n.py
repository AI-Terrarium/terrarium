"""Shared locale data and GitHub-compatible navigation for the catalog."""

import html
import json
from pathlib import Path
import re


LOCALES = json.loads(Path(__file__).with_name("locales.json").read_text())
CONTENT_ORDER = ("games", "scenes", "videos", "tools", "visualizations", "wallpapers")
ICONS = dict(zip(CONTENT_ORDER, ("🎮", "🌍", "🎬", "🛠️", "📊", "🖥️")))
GENRE_SLUGS = ("shooter", "action-and-combat", "platformer-and-runner", "racing-and-driving",
               "flight", "sports", "adventure-and-exploration", "puzzle", "strategy-and-management",
               "sandbox", "casual-and-arcade", "interactive-story", "simulation-and-visualization", "other-games")


def translate(code, key, **values):
    return LOCALES[code]["ui"][key].format(**values)


def language_bar(code):
    links = [f'<b>{html.escape(profile["name"])}</b>' if key == code else
             f'<a href="{profile["filename"]}">{html.escape(profile["name"])}</a>'
             for key, profile in LOCALES.items()]
    return '<p align="center"><sub>' + " · ".join(links[:5]) + '<br>' + " · ".join(links[5:]) + '</sub></p>'


def localize_markup(markup, code):
    """Translate catalog UI, leaving work names, licenses and creator text intact."""
    ui = LOCALES[code]["ui"]
    for source, target in ((">Code</a>", f'>{html.escape(ui["code"])}</a>'),
                           (">Files</a>", f'>{html.escape(ui["files"])}</a>'),
                           ("License unknown", html.escape(ui["unknown"])),
                           ("Works without a preview image:", html.escape(ui["no_preview"]))):
        markup = markup.replace(source, target)
    markup = re.sub(r"Collection of ([\d,]+) works",
                    lambda match: html.escape(ui["collection"].format(count=match[1])), markup)
    for original, translated in zip(("Work", "Creator", "License", "Links"), LOCALES[code]["headers"]):
        markup = markup.replace(f'>{original}</th>', f'>{html.escape(translated)}</th>')
    return markup

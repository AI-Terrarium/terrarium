"""Validate every locale, source count and relative navigation destination."""
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from i18n import CONTENT_ORDER, LOCALES, page_path, relative_link
from refresh_showcase import ROOT, load_catalog


class Document(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.links, self.anchors = [], set()
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.anchors.update(attrs[key] for key in ('name', 'id') if key in attrs)
        self.links.extend(attrs[key] for key in ('href', 'src', 'srcset') if key in attrs)


def validate(root=ROOT):
    entries, _ = load_catalog(root)
    documents = {}
    for code, profile in LOCALES.items():
        for folder in ('', *CONTENT_ORDER):
            path = (root / page_path(code, folder or None)).resolve()
            assert path.is_file(), path
            markup = path.read_text()
            assert 'assets/logo.svg' in markup, path
            assert not any(old in markup for old in ('logo-light.svg', 'logo-dark.svg', 'assets/mark.svg')), path
            doc = Document(markup)
            documents[path] = doc
            if not folder:
                assert re.findall(r'^## (.+)$', markup, re.M) == profile['nav'], path
                assert all(f'contents-{cat}' in doc.anchors for cat in CONTENT_ORDER), path
                assert markup.count('<!-- SHOWCASE:START -->') == 1, path
            else:
                assert '<!-- CATALOG:START -->' in markup, path
            for other_code, other in LOCALES.items():
                link = relative_link(page_path(code, folder or None), page_path(other_code, folder or None))
                assert link in doc.links or other_code == code, (path, link)
    checked = 0
    for path, document in documents.items():
        for value in document.links:
            url = urlsplit(value)
            if url.scheme or url.netloc:
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            assert target.exists(), (path, value)
            if url.fragment and target in documents:
                assert unquote(url.fragment) in documents[target].anchors, (path, value)
            checked += 1
    print(f'Validated {len(documents)} pages, {checked} local links and {len(entries)} catalog entries')


if __name__ == '__main__':
    validate()

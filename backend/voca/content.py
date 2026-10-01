import hashlib
import re
import time
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree
from .network import fetch_public
from .security import Problem, origin

class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.title = [], [], []
        self.ignore = 0
        self.in_title = False
        self.noindex = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'svg', 'template'):
            self.ignore += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'meta' and a.get('name', '').lower() in ('robots', 'vocabot') and 'noindex' in a.get('content', '').lower():
            self.noindex = True
        if not self.ignore:
            if tag == 'a' and a.get('href'):
                self.links.append(a['href'])
            if tag == 'img' and a.get('alt'):
                self.text.append(a['alt'])
            if tag in ('p', 'div', 'br', 'h1', 'h2', 'h3', 'li', 'tr'):
                self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg', 'template') and self.ignore:
            self.ignore -= 1
        if tag == 'title':
            self.in_title = False
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3') and not self.ignore:
            self.text.append('\n')

    def handle_data(self, value):
        if not self.ignore:
            self.text.append(value)
            if self.in_title:
                self.title.append(value)


def clean(html):
    p = Extractor()
    p.feed(str(html))
    return re.sub(r'[ \t]+', ' ', re.sub(r'\n\s*\n+', '\n', ''.join(p.text))).strip()


def chunks(text, size=1400, overlap=180):
    text = clean(text)[:100_000]
    for start in range(0, len(text), size - overlap):
        section = text[start:start + size].strip()
        if section:
            yield section


def fingerprint(doc):
    return hashlib.sha256((doc['title'] + '\n' + doc['text']).encode()).hexdigest()


def canonical(url, base):
    try:
        u = urlsplit(urljoin(base + '/', url))
        if origin(urlunsplit(u)) != base or u.query:
            return None
        path = u.path or '/'
        if re.search(r'/(cart|checkout|account|wp-admin|wp-login|search)(/|\.|$)', path, re.I):
            return None
        if re.search(r'\.(pdf|zip|png|jpg|jpeg|webp|gif|mp4|css|js|xml|json)$', path, re.I):
            return None
        return base + path
    except Problem:
        return None


def crawl(base, limit=300, progress=None):
    """Published HTML only. Sitemap discovery + same-origin link traversal; robots-aware."""
    robot = RobotFileParser()
    robot.set_url(base + '/robots.txt')
    try:
        raw, _, _ = fetch_public(base + '/robots.txt', base)
        robot.parse(raw.decode('utf-8', 'replace').splitlines())
    except Problem as e:
        if 'HTTP 404' in str(e):
            robot.parse([])
        else:
            raise Problem('Could not read robots.txt; scan stopped without changing the index.', 502)
    queue = deque([base + '/'])
    sitemaps = deque([base + '/sitemap.xml'] + (robot.site_maps() or []))
    seen_maps = set()
    while sitemaps and len(seen_maps) < 50:
        location = sitemaps.popleft()
        if location in seen_maps or origin(location) != base:
            continue
        seen_maps.add(location)
        try:
            raw, _, _ = fetch_public(location, base)
            root = ElementTree.fromstring(raw)
            is_index = root.tag.endswith('sitemapindex')
            for el in root.iter():
                if el.tag.endswith('}loc') or el.tag == 'loc':
                    if is_index:
                        sitemaps.append(el.text or '')
                    else:
                        target = canonical(el.text or '', base)
                        if target:
                            queue.append(target)
        except (Problem, ElementTree.ParseError):
            continue
    seen, docs, errors = set(), [], []
    while queue and len(seen) < limit:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not robot.can_fetch('VocaBot', url):
            continue
        try:
            raw, kind, final = fetch_public(url, base)
            if 'text/html' not in kind:
                continue
            p = Extractor()
            p.feed(raw.decode('utf-8', 'replace'))
            if p.noindex:
                continue
            text = clean(''.join(p.text))
            if text:
                docs.append({'id': 'web:' + final, 'url': final, 'title': ''.join(p.title).strip() or urlsplit(final).path, 'text': text, 'kind': 'page'})
            for link in p.links:
                target = canonical(urljoin(final, link), base)
                if target and target not in seen and len(queue) < limit * 20:
                    queue.append(target)
            if progress:
                progress(len(docs))
        except (Problem, OSError) as e:
            errors.append({'url': url, 'error': str(e)})
        time.sleep(0.15)
    if not docs:
        raise Problem('No accessible published HTML pages were found. Check the website address and robots.txt.', 502)
    return docs, {'pages': len(docs), 'limit_reached': bool(queue), 'errors': errors[:20]}

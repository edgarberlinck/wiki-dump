#!/usr/bin/env python3
"""Dump Wikipedia articles and their related articles to a Gotenberg PDF."""

import argparse
from collections import deque
from dataclasses import dataclass, field
from html import escape
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_URL = "https://en.wikipedia.org/w/api.php"
WIKI_URL = "https://en.wikipedia.org"


@dataclass
class Article:
    page_id: int
    title: str
    html: str
    links: list[str]
    aliases: list[str] = field(default_factory=list)


def title_key(title: str) -> str:
    """Match Wikipedia's underscore, Unicode and first-letter normalization."""
    title = unicodedata.normalize("NFC", title.replace("_", " ").strip())
    return title[:1].upper() + title[1:]


class WikipediaClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "wiki-dump/1.0 (Wikipedia PDF exporter)"
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def query(self, **params):
        response = self.session.get(
            API_URL, params={"format": "json", **params}, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("info", "Wikipedia API error"))
        return data

    def resolve_title(self, subject: str) -> str:
        data = self.query(
            action="query", list="search", srsearch=subject, srlimit=1
        )
        results = data.get("query", {}).get("search", [])
        if not results:
            raise RuntimeError(f"No Wikipedia article found for '{subject}'")
        return results[0]["title"]

    def fetch_article(self, title: str) -> Article:
        # parse returns the full article and every link, without query pagination.
        data = self.query(
            action="parse", page=title, prop="text|links", redirects=1
        )["parse"]
        return Article(
            page_id=data["pageid"],
            title=data["title"],
            html=data["text"]["*"],
            links=[
                link["*"]
                for link in data.get("links", [])
                if link.get("ns") == 0 and "exists" in link
            ],
        )


def collect_articles(client, title: str, depth: int, max_articles: int):
    """Breadth-first traversal; canonical page IDs prevent redirect cycles."""
    pending = deque([(title, 0)])
    scheduled = {title_key(title)}
    visited = {}
    articles = []
    while pending and len(articles) < max_articles:
        requested_title, level = pending.popleft()
        try:
            article = client.fetch_article(requested_title)
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as exc:
            if not articles:
                raise RuntimeError(
                    f"Could not fetch starting article '{requested_title}': {exc}"
                ) from exc
            print(f"Warning: skipping '{requested_title}': {exc}", file=sys.stderr)
            continue
        scheduled.add(title_key(article.title))
        if article.page_id in visited:
            visited[article.page_id].aliases.append(requested_title)
            continue
        article.aliases.append(requested_title)
        visited[article.page_id] = article
        articles.append(article)
        print(f"[{len(articles)}/{max_articles}] {article.title} (depth {level})")
        if level < depth:
            for link in article.links:
                key = title_key(link)
                if key not in scheduled:
                    scheduled.add(key)
                    pending.append((link, level + 1))
    if pending:
        print(
            f"Warning: stopped at {max_articles} articles; "
            "increase --max-articles to include more.",
            file=sys.stderr,
        )
    return articles


def article_url(title: str) -> str:
    return f"{WIKI_URL}/wiki/{quote(title.replace(' ', '_'), safe='')}"


def build_html(articles) -> str:
    """Make one self-contained, UTF-8 document with working article links."""
    included = {
        title_key(title): article.page_id
        for article in articles
        for title in [article.title, *article.aliases]
    }
    contents = []
    sections = []
    for article in articles:
        anchor = f"article-{article.page_id}"
        contents.append(
            f'<li><a href="#{anchor}">{escape(article.title)}</a></li>'
        )
        soup = BeautifulSoup(article.html, "html.parser")
        for element in soup.select(
            "script, style, link, base, meta, iframe, object, embed, form, "
            "img, picture, audio, video, source, .mw-editsection"
        ):
            element.decompose()
        for element in soup.find_all(True):
            # Do not let article markup load external assets or execute scripts.
            for attr in list(element.attrs):
                if attr.startswith("on") or attr in {
                    "style", "src", "srcset", "background", "action", "formaction"
                }:
                    del element[attr]
            for attr in ("id", "name"):
                if element.get(attr):
                    element[attr] = f"{anchor}-{element[attr]}"
            if element.name != "a" or not element.get("href"):
                continue
            href = element["href"]
            if href.startswith("#"):
                element["href"] = f"#{anchor}-{href[1:]}"
                continue
            url = urlsplit(urljoin(WIKI_URL, href))
            if url.scheme not in {"http", "https"}:
                del element["href"]
                continue
            if url.netloc == "en.wikipedia.org" and url.path.startswith("/wiki/"):
                target = title_key(unquote(url.path[len("/wiki/"):]))
                page_id = included.get(target)
                if page_id is not None:
                    fragment = f"-{url.fragment}" if url.fragment else ""
                    element["href"] = f"#article-{page_id}{fragment}"
                    continue
            element["href"] = url.geturl()
        sections.append(
            f'<section class="article" id="{anchor}">'
            f"<h1>{escape(article.title)}</h1>"
            f'<p class="source">Source: <a href="{article_url(article.title)}">'
            f"{escape(article.title)} - Wikipedia</a></p>{soup}</section>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(articles[0].title)}</title>"
        "<style>"
        "body{font-family:Arial,sans-serif;font-size:11pt;line-height:1.45;"
        "overflow-wrap:anywhere}"
        "h1,h2,h3{break-after:avoid}a{color:#0645ad}"
        ".article{break-before:page}.source{font-size:9pt;color:#555}"
        "table{border-collapse:collapse;max-width:100%;font-size:9pt}"
        "td,th{border:1px solid #ccc;padding:4px}"
        "pre{white-space:pre-wrap}.navbox,.vertical-navbox{display:none}"
        "</style></head><body>"
        f"<h1>{escape(articles[0].title)} - collected articles</h1>"
        f"<p>{len(articles)} articles. Content from Wikipedia; attribution and "
        'license details are available on each linked source page. '
        '<a href="https://creativecommons.org/licenses/by-sa/4.0/">'
        "CC BY-SA 4.0</a>.</p>"
        f"<ol>{''.join(contents)}</ol>{''.join(sections)}</body></html>"
    )


def write_pdf(html: str, output: Path, gotenberg_url: str):
    response = requests.post(
        f"{gotenberg_url.rstrip('/')}/forms/chromium/convert/html",
        files={"files": ("index.html", html.encode("utf-8"), "text/html")},
        data={"printBackground": "true", "preferCssPageSize": "true"},
        timeout=180,
    )
    response.raise_for_status()
    if not response.content.startswith(b"%PDF-"):
        raise RuntimeError("Gotenberg returned a non-PDF response")
    output.write_bytes(response.content)


def nonnegative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive_int(value):
    number = nonnegative_int(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("subject", nargs="+", help="Wikipedia subject to search")
    parser.add_argument(
        "--depth", type=nonnegative_int, default=2,
        help="link levels to follow (default: 2; 0 means only the main article)",
    )
    parser.add_argument(
        "--max-articles", type=positive_int, default=100,
        help="maximum articles including the main article (default: 100)",
    )
    parser.add_argument(
        "--gotenberg-url",
        default=os.environ.get("GOTENBERG_URL", "http://127.0.0.1:3000"),
        help="Gotenberg base URL (default: GOTENBERG_URL or http://127.0.0.1:3000)",
    )
    parser.add_argument("--output", type=Path, help="output PDF path")
    args = parser.parse_args(argv)
    subject = " ".join(args.subject).strip()
    if not subject:
        parser.error("subject must not be empty")
    filename = re.sub(r"[^\w.-]+", "_", subject).strip("._") or "wikipedia"
    output = args.output or Path(f"{filename}.pdf")
    client = WikipediaClient()
    try:
        title = client.resolve_title(subject)
        articles = collect_articles(client, title, args.depth, args.max_articles)
        write_pdf(build_html(articles), output, args.gotenberg_url)
    except (requests.RequestException, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.session.close()
    print(f"PDF saved as {output} ({len(articles)} articles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

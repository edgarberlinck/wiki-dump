import contextlib
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
import requests

import dump


class TraversalTests(unittest.TestCase):
    def collect(self, pages, depth=2, max_articles=100):
        client = Mock()
        client.fetch_article.side_effect = lambda title: pages[title]
        with contextlib.redirect_stdout(StringIO()):
            articles = dump.collect_articles(client, "Ramones", depth, max_articles)
        return articles, client

    def test_breadth_first_cycles_shared_links_and_redirects(self):
        pages = {
            "Ramones": dump.Article(
                1, "Ramones", "<p>Band</p>",
                ["Joey Ramone", "Johnny Ramone", "The Ramones"],
            ),
            "Joey Ramone": dump.Article(
                2, "Joey Ramone", "<p>Singer</p>", ["Ramones", "Shared album"]
            ),
            "Johnny Ramone": dump.Article(
                3, "Johnny Ramone", "<p>Guitarist</p>", ["Shared album", "Ramones"]
            ),
            "The Ramones": dump.Article(1, "Ramones", "<p>Band</p>", ["Joey Ramone"]),
            "Shared album": dump.Article(4, "Shared album", "<p>Album</p>", []),
        }
        articles, client = self.collect(pages)
        self.assertEqual(
            [article.title for article in articles],
            ["Ramones", "Joey Ramone", "Johnny Ramone", "Shared album"],
        )
        self.assertEqual(
            [call.args[0] for call in client.fetch_article.call_args_list],
            ["Ramones", "Joey Ramone", "Johnny Ramone", "The Ramones", "Shared album"],
        )
        self.assertIn("The Ramones", articles[0].aliases)

    def test_depth_and_article_caps(self):
        pages = {
            "Ramones": dump.Article(1, "Ramones", "Band", ["Joey Ramone"]),
            "Joey Ramone": dump.Article(2, "Joey Ramone", "Singer", ["Solo album"]),
            "Solo album": dump.Article(3, "Solo album", "Album", []),
        }
        for depth, cap, expected in [(0, 100, 1), (1, 100, 2), (2, 1, 1)]:
            with self.subTest(depth=depth, cap=cap):
                with contextlib.redirect_stderr(StringIO()):
                    articles, client = self.collect(pages, depth, cap)
                self.assertEqual(len(articles), expected)
                self.assertEqual(client.fetch_article.call_count, expected)

    def test_failed_related_article_does_not_abort_remaining_queue(self):
        client = Mock()
        client.fetch_article.side_effect = [
            dump.Article(1, "Ramones", "Band", ["Missing", "Joey Ramone"]),
            requests.Timeout("timed out"),
            dump.Article(2, "Joey Ramone", "Singer", []),
        ]
        with contextlib.redirect_stdout(StringIO()):
            with contextlib.redirect_stderr(StringIO()) as errors:
                articles = dump.collect_articles(client, "Ramones", 1, 10)
        self.assertEqual([article.page_id for article in articles], [1, 2])
        self.assertIn("skipping 'Missing'", errors.getvalue())

    def test_failed_starting_article_aborts(self):
        client = Mock()
        client.fetch_article.side_effect = requests.Timeout("timed out")
        with self.assertRaisesRegex(RuntimeError, "starting article"):
            dump.collect_articles(client, "Ramones", 2, 100)


class WikipediaTests(unittest.TestCase):
    def test_fetches_full_html_and_all_existing_main_namespace_links(self):
        client = dump.WikipediaClient()
        self.addCleanup(client.session.close)
        links = [{"ns": 0, "*": f"Article {n}", "exists": ""} for n in range(600)]
        links += [
            {"ns": 1, "*": "Talk:Ramones", "exists": ""},
            {"ns": 0, "*": "Missing article"},
        ]
        response = Mock()
        response.json.return_value = {
            "parse": {
                "pageid": 1, "title": "Ramones",
                "text": {"*": "<p>Intro</p><h2>History</h2><p>Full text</p>"},
                "links": links,
            }
        }
        with patch.object(client.session, "get", return_value=response) as get:
            article = client.fetch_article("The Ramones")
        self.assertEqual(len(article.links), 600)
        self.assertIn("Full text", article.html)
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["prop"], "text|links")
        self.assertEqual(params["redirects"], 1)

    def test_api_errors_are_reported(self):
        client = dump.WikipediaClient()
        self.addCleanup(client.session.close)
        response = Mock()
        response.json.return_value = {"error": {"info": "Page not found"}}
        with patch.object(client.session, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Page not found"):
                client.fetch_article("Missing")


class HtmlTests(unittest.TestCase):
    def test_unicode_internal_links_redirect_aliases_and_unique_fragments(self):
        articles = [
            dump.Article(
                1, "Ramones", '<h2 id="History">História</h2>'
                '<a href="#History">History</a>'
                '<a href="/wiki/Joey_Ramone#History">Joey</a>'
                '<a href="/wiki/Uncollected">Other</a>', [],
            ),
            dump.Article(
                2, "Joey Ramone", '<h2 id="History">Joey</h2>'
                '<a href="/wiki/The_Ramones">Band</a>', [],
            ),
        ]
        articles[0].aliases = ["The Ramones"]
        html = dump.build_html(articles)
        soup = BeautifulSoup(html, "html.parser")
        self.assertIn("História", html)
        self.assertIsNotNone(soup.find(id="article-1-History"))
        self.assertIsNotNone(soup.find(id="article-2-History"))
        self.assertEqual(soup.find("a", string="History")["href"], "#article-1-History")
        self.assertEqual(soup.find("a", string="Joey")["href"], "#article-2-History")
        self.assertEqual(soup.find("a", string="Band")["href"], "#article-1")
        self.assertEqual(
            soup.find("a", string="Other")["href"],
            "https://en.wikipedia.org/wiki/Uncollected",
        )
        self.assertEqual(
            [section["id"] for section in soup.select("section.article")],
            ["article-1", "article-2"],
        )

    def test_escapes_titles_and_removes_remote_assets_and_scripts(self):
        article = dump.Article(
            1, "A < B", '<script>alert(1)</script><img src="https://example.com/a">'
            '<p style="background:url(https://example.com)" onclick="alert(1)">Text</p>'
            '<a href="javascript:alert(1)">Bad</a>', [],
        )
        html = dump.build_html([article])
        self.assertIn("A &lt; B", html)
        soup = BeautifulSoup(html, "html.parser")
        self.assertIsNone(soup.find("script"))
        self.assertIsNone(soup.find("img"))
        self.assertEqual(soup.find("p", string="Text").attrs, {})
        self.assertNotIn("href", soup.find("a", string="Bad").attrs)


class PdfTests(unittest.TestCase):
    @patch("dump.requests.post")
    def test_posts_utf8_html_to_gotenberg(self, post):
        post.return_value.content = b"%PDF-1.7\nexample"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out" / "nested" / "dump.pdf"
            dump.write_pdf("<html>História</html>", output, "http://gotenberg:3000/")
            self.assertEqual(output.read_bytes(), b"%PDF-1.7\nexample")
        self.assertEqual(
            post.call_args.args[0],
            "http://gotenberg:3000/forms/chromium/convert/html",
        )
        name, content, mime = post.call_args.kwargs["files"]["files"]
        self.assertEqual(name, "index.html")
        self.assertEqual(content.decode("utf-8"), "<html>História</html>")
        self.assertEqual(mime, "text/html")

    @patch("dump.requests.post")
    def test_invalid_response_does_not_overwrite_existing_pdf(self, post):
        post.return_value.content = b"not a PDF"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dump.pdf"
            output.write_bytes(b"existing")
            with self.assertRaisesRegex(RuntimeError, "non-PDF"):
                dump.write_pdf("html", output, "http://gotenberg:3000")
            self.assertEqual(output.read_bytes(), b"existing")


class CliTests(unittest.TestCase):
    @patch("dump.write_pdf")
    @patch("dump.WikipediaClient")
    def test_default_output_directory_and_explicit_override(self, client_class, write_pdf):
        client = client_class.return_value
        client.resolve_title.return_value = "Ramones"
        client.fetch_article.return_value = dump.Article(1, "Ramones", "<p>Band</p>", [])
        for options, expected in [
            ([], Path("out/The_Ramones.pdf")),
            (["--output", "custom/band.pdf"], Path("custom/band.pdf")),
        ]:
            with self.subTest(options=options):
                with contextlib.redirect_stdout(StringIO()):
                    result = dump.main(["The Ramones", *options])
                self.assertEqual(result, 0)
                self.assertEqual(write_pdf.call_args.args[1], expected)


if __name__ == "__main__":
    unittest.main()

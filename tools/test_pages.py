#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The project site: every link lands, every local term resolves at its own URI, and
the files machines read are well formed."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import pages

try:
    import markdown_it  # noqa: F401
    HAVE_MARKDOWN = True
except ImportError:
    HAVE_MARKDOWN = False


class TestPaths(unittest.TestCase):

    def test_anchors_are_githubs(self):
        """A link written while reading on GitHub has to land on the site too."""
        self.assertEqual(pages.slug("Q4c. The durable namespace for local vocabulary terms"),
                         "q4c-the-durable-namespace-for-local-vocabulary-terms")
        self.assertEqual(pages.slug("§3.4 Observed properties"), "34-observed-properties")
        self.assertEqual(pages.slug("Raw — and calibrated"), "raw--and-calibrated")
        self.assertEqual(pages.slug("`snake_case` stays"), "snake_case-stays")

    def test_relative_urls(self):
        self.assertEqual(pages.relative("docs/spec/v0.1.html", "index.html"),
                         "docs/spec/v0.1.html")
        self.assertEqual(pages.relative("index.html", "docs/spec/v0.1.html"), "../../")
        self.assertEqual(pages.relative("docs/notes/index.html", "docs/notes/index.html"), "./")
        self.assertEqual(pages.relative("sdk/index.html", "docs/VIRTUAL_FARM.html"), "../sdk/")

    def test_term_docs_are_the_comment_above(self):
        source = "#: First line.\n#:\n#: More.\nFOO = LOCAL + \"foo/\"\nBAR = CF + \"bar/\"\n"
        self.assertEqual(pages.term_docs(source), {"FOO": ["First line.", "", "More."]})


@unittest.skipUnless(HAVE_MARKDOWN, "markdown-it-py is not installed")
class TestBuild(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = cls.tmp / "site"
        cls.report = pages.build(cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def file_for(self, url: str) -> Path:
        self.assertTrue(url.startswith(pages.BASE), url)
        path = url[len(pages.BASE):]
        return self.out / (path + "index.html" if path == "" or path.endswith("/") else path)

    def test_no_dangling_links(self):
        self.assertEqual(self.report.dangling, [])

    def test_no_links_to_missing_sections(self):
        self.assertEqual(self.report.fragments, [])

    def test_every_local_term_resolves_at_its_uri(self):
        """Q4c: the URIs in sdk/vocab.py are only worth having if they resolve."""
        vocab = pages._load_vocab()
        local = vocab.local_terms()
        self.assertTrue(local)
        for uri in local:
            text = self.file_for(uri).read_text(encoding="utf-8")
            self.assertIn(f'"@id": "{uri}"', text)
        skos = json.loads((self.out / "vocab" / "vocab.jsonld").read_text(encoding="utf-8"))
        self.assertLessEqual(set(local), {node["@id"] for node in skos["@graph"]})

    def test_sitemap_lists_every_page_once(self):
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [e.text for e in ET.parse(self.out / "sitemap.xml").findall("s:url/s:loc", ns)]
        self.assertEqual(len(locs), len(self.report.pages))
        self.assertEqual(len(locs), len(set(locs)))
        for loc in locs:
            self.assertTrue(self.file_for(loc).is_file(), loc)

    def test_robots_names_the_sitemap(self):
        self.assertIn(f"Sitemap: {pages.BASE}sitemap.xml",
                      (self.out / "robots.txt").read_text(encoding="utf-8"))

    def test_llms_txt_is_shaped_and_its_links_resolve(self):
        text = (self.out / "llms.txt").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# fieldmesh\n\n> "))
        links = re.findall(r"\]\((https://[^)]+)\)", text)
        self.assertGreater(len(links), 10)
        for url in links:
            self.assertTrue(self.file_for(url).is_file(), url)

    def test_every_page_has_jsonld_and_a_canonical(self):
        for p in self.report.pages:
            text = (self.out / p.out).read_text(encoding="utf-8")
            m = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
            self.assertIsNotNone(m, p.out)
            self.assertIn("@context", json.loads(m.group(1)), p.out)
            self.assertIn(f'<link rel="canonical" href="{pages.absolute(p.out)}">', text)

    def test_translations_name_each_other(self):
        en = next(p for p in self.report.pages if p.src.endswith("advise-mcallister.en.md"))
        es = next(p for p in self.report.pages if p.src.endswith("advise-mcallister.es.md"))
        self.assertEqual(en.alternates, es.alternates)
        self.assertEqual(es.lang, "es")


if __name__ == "__main__":
    unittest.main()

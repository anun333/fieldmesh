#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The project site, built from the repository's own Markdown.

    python3 tools/pages.py _site          # build into _site/
    python3 tools/pages.py --card PATH    # redraw the social-card image (needs Pillow)

Every tracked Markdown file is rendered to HTML at the same path, a `README.md`
becoming its directory's `index.html`. Links between published files stay on the
site and keep working with their fragments; links to code go to GitHub. A directory
with Markdown in it and no README gets a generated listing.

Beside the pages go the files machines look for:

* `robots.txt` and `sitemap.xml`, each page dated by its last commit. A crawler reads
  `robots.txt` only at the root of a host, and a project site is not the root of
  `anun333.github.io`, so the file here is for tools that look beside a site; the
  sitemap still has to be submitted, or named from the host's root.
* `llms.txt` (llmstxt.org) and `llms-full.txt`, with every page's Markdown published
  at its repository path, so a language model can read the source, not the rendering.
* schema.org JSON-LD on every page — `SoftwareSourceCode` on the front page,
  `TechArticle` on documents, `DefinedTerm` on vocabulary terms — with OpenGraph,
  canonical links, and `hreflang` between the English and Spanish advisor examples.

And the term pages that make the local vocabulary URIs in `sdk/vocab.py` resolve
(open-questions Q4c): one page per term at the path its URI names, labelled in every
language pack that has the term, and the whole set as SKOS JSON-LD.

Needs `markdown-it-py` (requirements-tools.txt), which nothing else here uses.
"""
from __future__ import annotations

import html
import importlib.util
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "pages_assets"

BASE = "https://anun333.github.io/fieldmesh/"
REPO = "https://github.com/anun333/fieldmesh"
NAME = "fieldmesh"
TAGLINE = "Layer zero of a farmer-owned farm stack"
SUMMARY = ("The data and device contract underneath everything else: what a reading is, "
           "what a device is, how a reading crosses an unreliable radio link, how its "
           "quality is judged, and how a farmer gets all of it back out.")
AUTHOR = {"@type": "Person", "name": "anun333", "url": "https://github.com/anun333"}
LICENCES = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "Apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
    "AGPL-3.0-or-later": "https://www.gnu.org/licenses/agpl-3.0.html",
}
KEYWORDS = ["agriculture", "farm data", "data sovereignty", "OGC SensorThings", "IoT",
            "soil moisture", "sensor data quality", "offline-first", "append-only log",
            "decision support", "climate adaptation", "LoRa"]

#: Directories that get a generated listing: title and one line saying what is in it.
LISTINGS = {
    "docs": ("Documentation", "The specification, the notes behind its decisions, and "
             "the guides."),
    "docs/spec": ("Specification", "The contract, every open decision with its options, "
                  "and the version it replaced."),
    "docs/notes": ("Notes", "The measurements and validations behind decisions: "
                   "encoding, power, FROST, QGIS, forecasts, public datasets, validation "
                   "sites."),
    "modules/advise/notes": ("Advisor notes", "Worked examples in English and Spanish, "
                             "and the reasoning behind the advisor's lists of plants, "
                             "animals and bees."),
}
NAV = (("Spec", "docs/spec/v0.1.md"), ("Open questions", "docs/spec/open-questions.md"),
       ("Notes", "docs/notes"), ("Advisor", "modules/advise/README.md"),
       ("Vocabulary", "vocab/index.html"))
#: llms.txt sections, in order; a page goes in the first whose test it passes.
SECTIONS = (
    ("Start here", lambda p: p in ("README.md", "docs/VIRTUAL_FARM.md", "CONTRIBUTING.md",
                                   "LICENSING.md", "GOVERNANCE.md", "docs/UNTESTED.md",
                                   "docs/LANGUAGE_PACKS.md")),
    ("Specification", lambda p: p in ("docs/spec/v0.1.md", "docs/spec/open-questions.md")),
    ("Components", lambda p: p.endswith("/README.md")),
    ("Notes", lambda p: p.startswith("docs/notes/")),
    ("Optional", lambda p: True),
)
#: What goes into llms-full.txt: everything but the optional section.
FULL = ("Start here", "Specification", "Components")

SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
LINK = re.compile(r'\b(href|src)="([^"]*)"')
HEADING = re.compile(r"<h([1-6])>(.*?)</h\1>", re.S)
SPDX = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)")


@dataclass
class Page:
    out: str                 # site path of the HTML
    title: str
    description: str
    body: str
    src: str = ""            # repository path it was built from; "" when generated
    lang: str = "en"
    licence: str = "CC-BY-4.0"
    modified: str = ""
    kind: str = "article"    # home | article | listing | term
    alternates: dict[str, str] = field(default_factory=dict)  # hreflang -> site path
    jsonld: dict | None = None


@dataclass
class Report:
    pages: list[Page] = field(default_factory=list)
    dangling: list[tuple[str, str]] = field(default_factory=list)
    fragments: list[tuple[str, str]] = field(default_factory=list)


# ------------------------------------------------------------------ repository

def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                              text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def tracked() -> list[str]:
    """Every tracked file, by repository path; the working tree when git is absent."""
    out = _git("ls-files", "-z")
    if out is not None:
        return sorted(p for p in out.split("\0") if p)
    return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()
                  and not any(s.startswith((".", "_")) for s in p.relative_to(ROOT).parts))


def last_changed(path: str = "") -> str:
    return (_git("log", "-1", "--format=%cs", "--", path or ".") or "").strip()


def licence_of(path: str) -> str:
    with open(ROOT / path, encoding="utf-8") as h:
        head = h.read(400)
    m = SPDX.search(head)
    return m.group(1) if m else "CC-BY-4.0"


# ------------------------------------------------------------------ text

def slug(text: str) -> str:
    """A heading's anchor, as GitHub makes it, so links written for GitHub still land."""
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def shorten(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:—– ") + "…"


def plain(inline) -> str:
    """The words of an inline token, without the markup."""
    words = []
    for child in inline.children or []:
        if child.type in ("text", "code_inline"):
            words.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            words.append(" ")
    return re.sub(r"\s+", " ", "".join(words)).strip()


def first_heading(tokens) -> str:
    for i, t in enumerate(tokens):
        if t.type == "heading_open" and t.tag == "h1":
            return plain(tokens[i + 1])
    return ""


def first_paragraph(tokens) -> str:
    """The first top-level paragraph that says what the page is, not its status."""
    for i, t in enumerate(tokens):
        if t.type == "paragraph_open" and t.level == 0:
            text = re.sub(r"^\d{4}-\d{2}-\d{2}\.\s+", "", plain(tokens[i + 1]))
            if len(text) >= 40 and not re.match(r"(status|draft|version)\b", text, re.I):
                return shorten(text)
    return ""


def without_title_and_lede(tokens) -> list:
    """Tokens minus the H1 and the paragraph after it, which the front page restates."""
    start = next(i for i, t in enumerate(tokens) if t.type == "heading_open" and t.tag == "h1")
    end = next(i for i, t in enumerate(tokens) if i > start and t.type == "paragraph_close"
               and t.level == 0)
    return tokens[:start] + tokens[end + 1:]


def anchor_headings(body: str) -> str:
    seen: dict[str, int] = {}

    def one(m: re.Match) -> str:
        level, inner = m.groups()
        base = slug(html.unescape(re.sub(r"<[^>]+>", "", inner)))
        n = seen.get(base, 0)
        seen[base] = n + 1
        hid = base if n == 0 else f"{base}-{n}"
        return (f'<h{level} id="{hid}">{inner}<a class="anchor" href="#{hid}" '
                f'aria-label="Link to this section">#</a></h{level}>')
    return HEADING.sub(one, body)


def wrap_tables(body: str) -> str:
    return body.replace("<table>", '<div class="table"><table>').replace(
        "</table>", "</table></div>")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


# ------------------------------------------------------------------ paths

def site_path(src: str) -> str:
    if posixpath.basename(src) == "README.md":
        return posixpath.join(posixpath.dirname(src), "index.html")
    return src[:-3] + ".html"


def relative(site: str, out: str) -> str:
    """The URL of site path `site` as written in the page at site path `out`."""
    directory = site.endswith("index.html")
    target = posixpath.dirname(site) if directory else site
    rel = posixpath.relpath(target or ".", posixpath.dirname(out) or ".")
    if directory:
        return "./" if rel == "." else rel + "/"
    return rel


def absolute(site: str) -> str:
    return BASE + (site[:-len("index.html")] if site.endswith("index.html") else site)


class Links:
    """Rewrites a rendered page's relative links: to the site where the target is
    published, to GitHub where it is only in the repository."""

    def __init__(self, files: list[str], published: dict[str, str], dirs: dict[str, str]):
        self.files = set(files)
        self.folders = {posixpath.dirname(f) for f in files}
        for f in list(self.folders):
            while f:
                f = posixpath.dirname(f)
                self.folders.add(f)
        self.published, self.dirs = published, dirs
        self.dangling: list[tuple[str, str]] = []

    def site(self, key: str) -> str | None:
        key = "" if key == "." else key.rstrip("/")
        return self.published.get(key) or self.dirs.get(key)

    def rewrite(self, body: str, src: str, out: str) -> str:
        here = posixpath.dirname(src)

        def one(m: re.Match) -> str:
            attr, url = m.groups()
            raw = html.unescape(url)
            if not raw or raw.startswith(("#", "/")) or SCHEME.match(raw):
                return m.group(0)
            path, _, frag = raw.partition("#")
            key = posixpath.normpath(posixpath.join(here, path)) if path else src
            key = "" if key == "." else key
            target = self.site(key)
            if key.startswith(".."):
                new = None
            elif target:
                new = relative(target, out)
            elif key in self.folders:
                new = f"{REPO}/tree/main/{key}"
            elif key in self.files:
                new = f"{REPO}/{'raw' if attr == 'src' else 'blob'}/main/{key}"
            else:
                new = None
            if new is None:
                self.dangling.append((src, raw))
                return m.group(0)
            return f'{attr}="{esc(new + ("#" + frag if frag else ""))}"'
        return LINK.sub(one, body)


# ------------------------------------------------------------------ pages

def _markdown():
    from markdown_it import MarkdownIt
    return MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])


def markdown_page(md, src: str, links: Links) -> Page:
    text = (ROOT / src).read_text(encoding="utf-8")
    tokens = md.parse(text)
    home = src == "README.md"
    title = first_heading(tokens) or posixpath.basename(src)
    description = SUMMARY if home else first_paragraph(tokens) or title
    if home:
        tokens = without_title_and_lede(tokens)
    out = site_path(src)
    body = md.renderer.render(tokens, md.options, {})
    body = links.rewrite(anchor_headings(wrap_tables(body)), src, out)
    lang = "es" if src.endswith(".es.md") else "en"
    return Page(out=out, title=title, description=description, body=body, src=src,
                lang=lang, licence=licence_of(src), modified=last_changed(src),
                kind="home" if home else "article")


def pair_languages(pages: list[Page]) -> None:
    """`x.en.md` and `x.es.md` name each other as translations."""
    by_src = {p.src: p for p in pages if p.src}
    for p in pages:
        m = re.match(r"(.*)\.(en|es)\.md$", p.src)
        if not m:
            continue
        for lang in ("en", "es"):
            other = by_src.get(f"{m.group(1)}.{lang}.md")
            if other:
                p.alternates[lang] = other.out


def listing_page(directory: str, pages: list[Page], dirs: dict[str, str]) -> Page:
    title, intro = LISTINGS.get(directory, (directory, ""))
    out = f"{directory}/index.html"
    items = sorted((p for p in pages if p.src and posixpath.dirname(p.src) == directory
                    and p.out != out), key=lambda p: (p.lang != "en", p.title.lower()))
    rows = []
    for sub, site in sorted(dirs.items()):
        if sub and posixpath.dirname(sub) == directory:
            label = LISTINGS.get(sub, (posixpath.basename(sub),))[0]
            blurb = LISTINGS.get(sub, ("", ""))[1]
            rows.append(f'<li><a href="{esc(relative(site, out))}">{esc(label)}</a>'
                        f"<p>{esc(blurb)}</p></li>")
    for p in items:
        lang = f' lang="{p.lang}"' if p.lang != "en" else ""
        rows.append(f'<li{lang}><a href="{esc(relative(p.out, out))}">{esc(p.title)}</a>'
                    f"<p>{esc(p.description)}</p></li>")
    body = (f'<h1 id="top">{esc(title)}</h1>\n<p class="lede">{esc(intro)}</p>\n'
            f'<ul class="listing">\n' + "\n".join(rows) + "\n</ul>\n")
    dated = [p.modified for p in items if p.modified]
    return Page(out=out, title=title, description=intro or title, body=body,
                kind="listing", modified=max(dated) if dated else "")


def _load_vocab():
    spec = importlib.util.spec_from_file_location("fieldmesh_site_vocab",
                                                  ROOT / "sdk" / "vocab.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def term_docs(source: str) -> dict[str, list[str]]:
    """The `#:` comment block above each `NAME = LOCAL + ...` line, by constant name."""
    docs: dict[str, list[str]] = {}
    block: list[str] = []
    for line in source.splitlines():
        s = line.strip()
        if s.startswith("#:"):
            block.append(s[3:] if s.startswith("#: ") else s[2:])
            continue
        m = re.match(r"([A-Z_][A-Z0-9_]*)\s*=\s*LOCAL\s*\+", s)
        if m:
            docs[m.group(1)] = block
        block = []
    return docs


def term_labels() -> dict[str, dict[str, str]]:
    """Every language pack's label for each term: {uri: {language: label}}."""
    labels: dict[str, dict[str, str]] = {}
    for pack in sorted((ROOT / "sdk" / "packs").glob("*.json")):
        data = json.loads(pack.read_text(encoding="utf-8"))
        lang = data.get("_meta", {}).get("language", pack.stem)
        for key, value in data.get("strings", data).items():
            if key.startswith("term."):
                labels.setdefault(key[5:], {})[lang] = value
    return labels


def vocab_pages(md, links: Links) -> tuple[list[Page], dict]:
    """A page per local term at the path its URI names, an index of every term, and
    the local terms as SKOS."""
    vocab = _load_vocab()
    source = (ROOT / "sdk" / "vocab.py").read_text(encoding="utf-8")
    docs, labels = term_docs(source), term_labels()
    modified, licence = last_changed("sdk/vocab.py"), licence_of("sdk/vocab.py")
    index_out = "vocab/index.html"
    q4c = links.site("docs/spec/open-questions.md")
    pages, concepts, local_rows = [], [], []
    for name, lines in sorted(docs.items()):
        uri = getattr(vocab, name)
        code = uri[len(vocab.LOCAL):].strip("/")
        out = f"vocab/{code}/index.html"
        text = "\n".join(lines).strip()
        definition, _, scope = text.partition("\n\n")
        definition = " ".join(definition.split())
        names = labels.get(uri, {})
        label = names.get("en", code.replace("_", " "))
        unit = vocab.TERMS.get(uri, ("", ""))[0]
        unit_cell = (f"<code>{esc(unit)}</code>" if unit is not None
                     else "none: a truth, open or shut (§3.4)")
        line = next(i for i, s in enumerate(source.splitlines(), 1)
                    if re.match(rf"\s*{name}\s*=", s))
        label_rows = "".join(f'<li lang="{esc(lang)}"><span class="code">{esc(lang)}</span> '
                             f"{esc(value)}</li>" for lang, value in sorted(names.items()))
        body = (
            f'<p class="kicker"><a href="../">Vocabulary</a> · local term</p>\n'
            f'<h1 id="top">{esc(label)}</h1>\n'
            f'<p class="uri"><code>{esc(uri)}</code></p>\n'
            f'<p class="lede">{esc(definition)}</p>\n'
            f'<dl class="facts">\n<dt>Unit (UCUM)</dt><dd>{unit_cell}</dd>\n'
            f'<dt>Labels</dt><dd><ul class="plain">{label_rows}</ul></dd>\n'
            f'<dt>Status</dt><dd>Local, because neither CF nor ODM2 has the term, and '
            f'owed upstream to ODM2. Its durable identifier will be a w3id.org address that '
            f'redirects here (<a href="{esc(relative(q4c, out))}#q4c-the-durable-namespace-'
            f'for-local-vocabulary-terms">Q4c</a>), so links to this page keep working.</dd>\n'
            f'<dt>Defined in</dt><dd><a href="{REPO}/blob/main/sdk/vocab.py#L{line}">'
            f"sdk/vocab.py</a></dd>\n</dl>\n")
        if scope:
            body += '<h2 id="scope-note">Scope note</h2>\n' + md.render(scope)
        body += (f'<p class="machine">As SKOS: <a href="../vocab.jsonld">vocab.jsonld</a>'
                 "</p>\n")
        jsonld = {"@context": "https://schema.org", "@type": "DefinedTerm", "@id": uri,
                  "name": label, "termCode": code, "description": definition,
                  "url": absolute(out), "inDefinedTermSet": {
                      "@type": "DefinedTermSet", "@id": vocab.LOCAL,
                      "name": "fieldmesh local vocabulary", "url": absolute(index_out)}}
        pages.append(Page(out=out, title=label, description=shorten(definition), body=body,
                          licence=licence, modified=modified, kind="term", jsonld=jsonld))
        concept = {"@id": uri, "@type": "skos:Concept", "skos:notation": code,
                   "skos:inScheme": {"@id": vocab.LOCAL},
                   "skos:prefLabel": [{"@value": v, "@language": k}
                                      for k, v in sorted(names.items())],
                   "skos:definition": {"@value": definition, "@language": "en"}}
        if scope:
            concept["skos:scopeNote"] = {"@value": " ".join(scope.split()),
                                         "@language": "en"}
        concepts.append(concept)
        local_rows.append(f'<tr><td><a href="{esc(relative(out, index_out))}">{esc(label)}'
                          f"</a></td><td><code>{esc(uri)}</code></td>"
                          f"<td>{unit_cell}</td></tr>")
    every = []
    for uri, (unit, src) in sorted(vocab.TERMS.items(), key=lambda kv: (kv[1][1], kv[0])):
        shown = relative(f"vocab/{uri[len(vocab.LOCAL):].strip('/')}/index.html", index_out) \
            if src == "local" else uri
        cell = f"<code>{esc(unit)}</code>" if unit is not None else "none (a truth)"
        every.append(f'<tr><td><a href="{esc(shown)}"><code>{esc(uri)}</code></a></td>'
                     f"<td>{cell}</td><td>{esc(src)}</td></tr>")
    body = (
        '<h1 id="top">Vocabulary</h1>\n'
        '<p class="lede">Every observed-property term fieldmesh uses, by URI, with the '
        "UCUM unit it is normally reported in. Measurands come from the CF Standard Names "
        "and sensor-plumbing terms from ODM2. A local term exists only for a gap in both, "
        "says why, and is owed upstream — so the local list is short on purpose.</p>\n"
        '<h2 id="local-terms">Local terms</h2>\n<div class="table"><table><thead><tr>'
        "<th>Term</th><th>URI</th><th>Unit</th></tr></thead><tbody>"
        + "".join(local_rows) + "</tbody></table></div>\n"
        '<h2 id="every-term">Every term</h2>\n<div class="table"><table><thead><tr>'
        "<th>URI</th><th>Unit</th><th>Source</th></tr></thead><tbody>"
        + "".join(every) + "</tbody></table></div>\n"
        f'<p class="machine">The local terms as SKOS: <a href="vocab.jsonld">vocab.jsonld'
        f'</a>. Defined in <a href="{REPO}/blob/main/sdk/vocab.py">sdk/vocab.py</a>; the '
        f'decision is <a href="{esc(relative(q4c, index_out))}#q4-unit-system-and-'
        f'observed-property-vocabulary">Q4</a>.</p>\n')
    pages.insert(0, Page(out=index_out, title="Vocabulary", description=shorten(
        "Every observed-property term fieldmesh uses, with its unit and source: CF "
        "Standard Names, ODM2, and the few local terms owed upstream."), body=body,
        licence=licence, modified=modified, kind="listing"))
    skos = {"@context": {"skos": "http://www.w3.org/2004/02/skos/core#",
                         "dct": "http://purl.org/dc/terms/"},
            "@graph": [{"@id": vocab.LOCAL, "@type": "skos:ConceptScheme",
                        "dct:title": "fieldmesh local vocabulary",
                        "dct:license": {"@id": LICENCES.get(licence, licence)},
                        "dct:source": {"@id": f"{REPO}/blob/main/sdk/vocab.py"},
                        "skos:hasTopConcept": [{"@id": c["@id"]} for c in concepts]},
                       *concepts]}
    return pages, skos


# ------------------------------------------------------------------ the document

def jsonld_for(page: Page, latest: str) -> dict:
    if page.jsonld:
        return page.jsonld
    url = absolute(page.out)
    if page.kind == "home":
        return {"@context": "https://schema.org", "@graph": [
            {"@type": "WebSite", "@id": BASE + "#website", "url": BASE, "name": NAME,
             "description": f"{TAGLINE}. {SUMMARY}", "inLanguage": "en",
             "publisher": AUTHOR},
            {"@type": "SoftwareSourceCode", "@id": BASE + "#software", "name": NAME,
             "description": f"{TAGLINE}. {SUMMARY}", "url": BASE, "codeRepository": REPO,
             "programmingLanguage": {"@type": "ComputerLanguage", "name": "Python"},
             "runtimePlatform": "Python 3.12", "author": AUTHOR,
             "license": [LICENCES[k] for k in ("Apache-2.0", "AGPL-3.0-or-later",
                                               "CC-BY-4.0")],
             "keywords": KEYWORDS, "isAccessibleForFree": True,
             "creativeWorkStatus": "pre-release", "dateModified": latest,
             "applicationCategory": "Agriculture",
             "operatingSystem": "Linux, macOS, Windows"}]}
    kind = "CollectionPage" if page.kind == "listing" else "TechArticle"
    data = {"@context": "https://schema.org", "@type": kind, "headline": page.title,
            "name": page.title, "description": page.description, "url": url,
            "inLanguage": page.lang, "author": AUTHOR,
            "license": LICENCES.get(page.licence, page.licence),
            "isPartOf": {"@type": "WebSite", "@id": BASE + "#website", "url": BASE},
            "about": {"@id": BASE + "#software"}}
    if page.modified:
        data["dateModified"] = page.modified
    return data


def document(page: Page, nav: list[tuple[str, str]], latest: str) -> str:
    prefix = relative("index.html", page.out)
    url = absolute(page.out)
    title = (f"{NAME} — {TAGLINE.lower()}" if page.kind == "home"
             else f"{page.title} · {NAME}")
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(title)}</title>",
        f'<meta name="description" content="{esc(page.description)}">',
        f'<link rel="canonical" href="{esc(url)}">',
        f'<meta property="og:type" content="{"website" if page.kind == "home" else "article"}">',
        f'<meta property="og:site_name" content="{NAME}">',
        f'<meta property="og:title" content="{esc(page.title if page.kind != "home" else title)}">',
        f'<meta property="og:description" content="{esc(page.description)}">',
        f'<meta property="og:url" content="{esc(url)}">',
        f'<meta property="og:image" content="{BASE}og.png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{NAME}: {esc(TAGLINE.lower())}">',
        f'<meta property="og:locale" content="{"es_ES" if page.lang == "es" else "en_US"}">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="color-scheme" content="light dark">',
        f'<link rel="icon" href="{prefix}favicon.svg" type="image/svg+xml">',
        f'<link rel="stylesheet" href="{prefix}site.css">',
        f'<link rel="sitemap" type="application/xml" href="{prefix}sitemap.xml">',
    ]
    if page.src:
        head.append(f'<link rel="alternate" type="text/markdown" href="{BASE}{page.src}">')
    for lang, site in sorted(page.alternates.items()):
        head.append(f'<link rel="alternate" hreflang="{lang}" href="{absolute(site)}">')
    if "en" in page.alternates:
        head.append(f'<link rel="alternate" hreflang="x-default" '
                    f'href="{absolute(page.alternates["en"])}">')
    ld = json.dumps(jsonld_for(page, latest), ensure_ascii=False, indent=1)
    head.append(f'<script type="application/ld+json">\n{ld.replace("</", "<" + chr(92) + "/")}'
                "\n</script>")
    links = []
    for label, site in nav:
        here = ' aria-current="page"' if site == page.out else ""
        links.append(f'<a href="{esc(relative(site, page.out))}"{here}>{esc(label)}</a>')
    links.append(f'<a href="{REPO}">GitHub</a>')
    if page.src:
        source = (f'Source: <a href="{REPO}/blob/main/{esc(page.src)}">{esc(page.src)}</a>'
                  f' (<a href="{BASE}{esc(page.src)}">Markdown</a>)')
    else:
        source = (f'Generated by <a href="{REPO}/blob/main/tools/pages.py">tools/pages.py'
                  "</a>")
    licence = (f'<a href="{LICENCES[page.licence]}" rel="license">{esc(page.licence)}</a>'
               if page.licence in LICENCES else esc(page.licence))
    changed = f" · Last changed {page.modified}" if page.modified else ""
    hero = ""
    if page.kind == "home":
        hero = (
            '<section class="hero">\n'
            '<p class="status">Pre-release · built against a simulated farm</p>\n'
            f"<h1>{NAME}</h1>\n"
            f'<p class="tagline">{esc(TAGLINE)}</p>\n'
            f'<p class="lede">{esc(SUMMARY)}</p>\n'
            '<p class="actions">'
            f'<a class="button primary" href="docs/spec/v0.1.html">Read the spec</a>'
            f'<a class="button" href="{REPO}">Source on GitHub</a>'
            f'<a class="button" href="docs/spec/open-questions.html">Open questions</a></p>\n'
            "</section>\n")
    return (
        f'<!doctype html>\n<html lang="{page.lang}">\n<head>\n' + "\n".join(head)
        + "\n</head>\n<body>\n"
        '<a class="skip" href="#content">Skip to content</a>\n'
        '<header class="top" lang="en">\n'
        f'<a class="brand" href="{prefix or "./"}"><img src="{prefix}favicon.svg" alt="" '
        f'width="22" height="22">{NAME}</a>\n'
        f'<nav aria-label="Site">{"".join(links)}</nav>\n</header>\n'
        f'<main id="content" class="{page.kind}">\n{hero}<article>\n{page.body}</article>\n'
        "</main>\n"
        f'<footer lang="en"><p>{source} · {licence}{changed}</p>\n'
        f'<p>{NAME} · docs CC-BY-4.0 · SDK, simulator and tools Apache-2.0 · server and '
        f'modules AGPL-3.0-or-later · <a href="{prefix}llms.txt">llms.txt</a></p></footer>\n'
        "</body>\n</html>\n")


NOT_FOUND = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found · {NAME}</title>
<meta name="robots" content="noindex">
<link rel="icon" href="{BASE}favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{BASE}site.css">
</head>
<body>
<header class="top"><a class="brand" href="{BASE}"><img src="{BASE}favicon.svg" alt=""
width="22" height="22">{NAME}</a></header>
<main id="content" class="article"><article>
<h1>Nothing at this address</h1>
<p class="lede">The page may have moved when its file did. Try the
<a href="{BASE}">front page</a>, the <a href="{BASE}docs/spec/v0.1.html">specification</a>,
or the <a href="{REPO}">repository</a>.</p>
</article></main>
</body>
</html>
"""


# ------------------------------------------------------------------ machine files

def robots() -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {BASE}sitemap.xml\n"


def sitemap(pages: list[Page]) -> str:
    rows = []
    for p in sorted(pages, key=lambda p: (p.kind != "home", p.out)):
        alt = "".join(f'\n    <xhtml:link rel="alternate" hreflang="{lang}" '
                      f'href="{absolute(site)}"/>' for lang, site in sorted(p.alternates.items()))
        mod = f"\n    <lastmod>{p.modified}</lastmod>" if p.modified else ""
        rows.append(f"  <url>\n    <loc>{esc(absolute(p.out))}</loc>{mod}{alt}\n  </url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(rows) + "\n</urlset>\n")


def _sections(pages: list[Page]) -> dict[str, list[Page]]:
    groups: dict[str, list[Page]] = {name: [] for name, _ in SECTIONS}
    for p in sorted((p for p in pages if p.src), key=lambda p: p.src):
        name = next(n for n, test in SECTIONS if test(p.src))
        groups[name].append(p)
    order = [n for n, _ in SECTIONS]
    first = {"README.md": 0, "docs/spec/v0.1.md": 0}
    for name in order:
        groups[name].sort(key=lambda p: (first.get(p.src, 1), p.src))
    return groups


def llms(pages: list[Page]) -> str:
    lines = [
        f"# {NAME}", "", f"> {TAGLINE}. {SUMMARY}", "",
        "Pre-release, built against a simulated farm: no hardware in the loop yet, no pilot "
        "farm, and no commands to pumps or valves. The contract is OGC SensorThings 1.1 over "
        "an append-only log the farmer owns, with quality judgements that carry their "
        "provenance. Python 3.12; one runtime dependency (cbor2). Documentation CC-BY-4.0; "
        "SDK, simulator and tools Apache-2.0; server and modules AGPL-3.0-or-later.",
        "", f"Every link below is the page's Markdown source. Repository: {REPO}",
    ]
    for name, group in _sections(pages).items():
        if not group:
            continue
        lines += ["", f"## {name}", ""]
        for p in group:
            lines.append(f"- [{p.title}]({BASE}{p.src}): {p.description}")
        if name == "Optional":
            lines.append(f"- [Vocabulary]({BASE}vocab/vocab.jsonld): the local "
                         "observed-property terms as SKOS JSON-LD")
    return "\n".join(lines) + "\n"


def llms_full(pages: list[Page]) -> str:
    parts = [f"# {NAME}\n\n> {TAGLINE}. {SUMMARY}\n"]
    for name, group in _sections(pages).items():
        if name in FULL:
            for p in group:
                text = (ROOT / p.src).read_text(encoding="utf-8")
                text = re.sub(r"^<!--.*?-->\s*", "", text, flags=re.S)
                parts.append(f"<!-- {BASE}{p.src} -->\n\n{text.strip()}\n")
    return "\n\n---\n\n".join(parts)


# ------------------------------------------------------------------ build

def check_fragments(pages: list[Page]) -> list[tuple[str, str]]:
    """Links into a page's sections whose section does not exist."""
    ids = {p.out: set(re.findall(r'\bid="([^"]+)"', p.body)) | {"top", "content"}
           for p in pages}
    broken = []
    for p in pages:
        for url in re.findall(r'\bhref="([^"]+)"', p.body):
            url = html.unescape(url)
            if SCHEME.match(url) or "#" not in url:
                continue
            path, _, frag = url.partition("#")
            target = posixpath.normpath(posixpath.join(posixpath.dirname(p.out), path)) \
                if path else p.out
            if path.endswith("/") or target in ("", "."):
                target = posixpath.join("" if target == "." else target, "index.html")
            if target in ids and frag not in ids[target]:
                broken.append((p.out, url))
    return broken


def build(out: Path) -> Report:
    md = _markdown()
    files = tracked()
    sources = [f for f in files if f.endswith(".md")]
    published = {src: site_path(src) for src in sources}
    dirs = {posixpath.dirname(s): published[s] for s in sources
            if posixpath.basename(s) == "README.md"}
    for d in {posixpath.dirname(s) for s in sources} - set(dirs):
        if d:
            dirs[d] = f"{d}/index.html"
    for d in LISTINGS:
        dirs.setdefault(d, f"{d}/index.html")
    links = Links(files, published, dirs)
    pages = [markdown_page(md, src, links) for src in sources]
    pair_languages(pages)
    readmes = {p.out for p in pages}
    for d in sorted(dirs):
        if dirs[d] not in readmes:
            pages.append(listing_page(d, pages, dirs))
    terms, skos = vocab_pages(md, links)
    pages += terms
    latest = last_changed()
    nav = [(label, links.site(target) or target) for label, target in NAV]

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for p in pages:
        path = out / p.out
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document(p, nav, latest), encoding="utf-8")
    for src in sources:
        (out / src).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / src, out / src)
    for asset in ASSETS.iterdir():
        if asset.is_file():
            shutil.copyfile(asset, out / asset.name)
    (out / "vocab" / "vocab.jsonld").write_text(
        json.dumps(skos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "404.html").write_text(NOT_FOUND, encoding="utf-8")
    (out / "robots.txt").write_text(robots(), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(pages), encoding="utf-8")
    (out / "llms.txt").write_text(llms(pages), encoding="utf-8")
    (out / "llms-full.txt").write_text(llms_full(pages), encoding="utf-8")
    return Report(pages=pages, dangling=links.dangling, fragments=check_fragments(pages))


# ------------------------------------------------------------------ social card

def card(path: Path) -> None:
    """The 1200x630 image link previews show. Drawn once and committed, because the
    fonts it needs are not on every machine that builds the site."""
    from PIL import Image, ImageDraw, ImageFont

    def font(bold: bool, size: int):
        names = (["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold
                 else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
        for base in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"):
            for n in names:
                if os.path.exists(os.path.join(base, n)):
                    return ImageFont.truetype(os.path.join(base, n), size)
        return ImageFont.load_default()

    paper, ink, green, muted = "#faf8f2", "#1c211d", "#2d6a3e", "#5b645c"
    img = Image.new("RGB", (1200, 630), paper)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1200, 14), fill=green)
    d.rectangle((0, 560, 1200, 630), fill="#efeadb")
    # the sprout of the favicon, at 6x
    x0, y0, s = 80, 92, 6
    d.rounded_rectangle((x0, y0, x0 + 32 * s, y0 + 32 * s), radius=7 * s, fill=green)
    d.line((x0 + 16 * s, y0 + 26 * s, x0 + 16 * s, y0 + 15 * s), fill=paper, width=int(2.4 * s))
    d.line((x0 + 8 * s, y0 + 26 * s, x0 + 24 * s, y0 + 26 * s), fill=paper, width=int(2.4 * s))

    def leaf(*curves):
        points = []
        for (ax, ay), (bx, by), (cx, cy), (ex, ey) in curves:
            for i in range(25):
                t = i / 24
                u = 1 - t
                points.append((x0 + s * (u**3 * ax + 3 * u * u * t * bx + 3 * u * t * t * cx
                                         + t**3 * ex),
                               y0 + s * (u**3 * ay + 3 * u * u * t * by + 3 * u * t * t * cy
                                         + t**3 * ey)))
        d.polygon(points, fill=paper)
    leaf(((16, 17), (16, 12), (19.5, 8.5), (25, 8.5)), ((25, 8.5), (25, 14), (21.5, 17), (16, 17)))
    leaf(((16, 20), (16, 16), (13.2, 13.2), (8.8, 13.2)),
         ((8.8, 13.2), (8.8, 17.6), (11.6, 20), (16, 20)))
    d.text((330, 100), NAME, font=font(True, 112), fill=ink)
    d.text((334, 238), TAGLINE, font=font(False, 40), fill=green)
    words, line, y, f = SUMMARY.split(), "", 340, font(False, 30)
    for w in words:
        trial = f"{line} {w}".strip()
        if d.textlength(trial, font=f) > 1040:
            d.text((80, y), line, font=f, fill=muted)
            line, y = w, y + 44
        else:
            line = trial
    d.text((80, y), line, font=f, fill=muted)
    d.text((80, 580), "anun333.github.io/fieldmesh  ·  OGC SensorThings 1.1  ·  "
           "Apache-2.0 · AGPL-3.0 · CC-BY-4.0", font=font(False, 22), fill=muted)
    img.save(path, optimize=True)


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--card":
        card(Path(argv[1]))
        return 0
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    report = build(Path(argv[0]))
    print(f"{len(report.pages)} pages into {argv[0]}")
    for src, url in report.dangling:
        print(f"dangling link in {src}: {url}", file=sys.stderr)
    for page, url in report.fragments:
        print(f"no such section, linked from {page}: {url}", file=sys.stderr)
    return 1 if report.dangling or report.fragments else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

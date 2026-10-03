#!/usr/bin/env python3
"""Build the static yomez.com site in docs/ from the Simply Static export.

Source: original/export (unzipped Simply Static export, plus pages fetched
from the live site that crashed mid-render). Output: docs/ (GitHub Pages).

Steps:
  1. Repair pages that crashed partway (CAPTCHA 4WP fatal error) by splicing
     in the footer from a cleanly exported post.
  2. Strip things that need a server: forms, search, comments, WP API links.
  3. Make yomez.com URLs root-relative (except canonical/og/JSON-LD).
  4. Drop demo/duplicate pages that no kept page links to.
  5. Copy only the assets the kept pages (and their CSS) reference.
"""
import json
import re
import shutil
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "original" / "export"
OUT = ROOT / "docs"
ORIGIN = "https://yomez.com"

# Theme-demo / duplicate pages: removed unless a kept page links to them.
JUNK_CANDIDATES = [
    "home1", "product1", "about-us1", "about-us1/doron-gan", "l1", "l2",
    "blog-image-medium", "blog-image-alternate-medium", "blog-full-content",
    "blog-2/blog-image-large", "subscribe-test", "getting-started-example",
    "blog-menu",
]
# Clean post used as the footer donor for crashed pages.
FOOTER_DONOR = "goal-setting-part-one"
MAX_FILE_BYTES = 95 * 1024 * 1024  # GitHub rejects files over 100 MB

ASSET_RE = re.compile(r"""/wp-(?:content|includes)/[^\s"'()<>\\,]+""")
CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)|@import\s+['"]([^'"]+)['"]""")


def page_key(path: Path) -> str:
    """'about-us/index.html' -> 'about-us'; root index -> ''."""
    return path.parent.relative_to(SRC).as_posix().strip(".")


def load_pages() -> dict[str, str]:
    pages = {}
    for f in SRC.rglob("index.html"):
        rel = f.relative_to(SRC).as_posix()
        if rel.startswith(("wp-content/", "wp-includes/")):
            continue
        pages[page_key(f)] = f.read_text(encoding="utf-8", errors="replace")
    return pages


def repair(html: str, footer: str, key: str) -> str:
    """Cut off the WordPress error page and append the donor footer."""
    cut = html.find("<!DOCTYPE html>", 100)
    if cut == -1:
        cut = html.find("<!doctype html>", 100)
    head = html[:cut].rstrip()
    if head.endswith('<div class="hb-sidebar col-3 hb-equal-col-height">'):
        head += "</div>"  # crashed inside the (widget-only) sidebar
    elif "END #single-blog-wrapper" in head[-300:]:
        head += "\n\t\t\t</div><!-- END .hb-main-content -->"
    else:
        sys.exit(f"Don't know how to repair crashed page: /{key}/")
    return head + "\n" + footer


def footer_from(html: str) -> str:
    i = html.index("</div><!-- END .row -->")
    return html[html.rfind("\n", 0, i) + 1:]


def links_in(html: str) -> set[str]:
    out = set()
    for m in re.finditer(r'href="https://yomez\.com/([^"#?]*)', html):
        out.add(m.group(1).strip("/"))
    return out


def relativize(text: str) -> str:
    text = text.replace(ORIGIN + "/", "/").replace(ORIGIN + '"', '/"')
    text = text.replace("https:\\/\\/yomez.com\\/", "\\/")
    text = text.replace("//yomez.com/", "/")
    return text


def remove_app_links(soup: BeautifulSoup) -> None:
    """Drop links to the retired Yomez web app (app.yomez.com no longer exists)."""
    # Header "Login" link.
    for el in soup.select("#top-custom-link-widget"):
        el.decompose()
    # "Create Account" buttons (each alone in its row) and button images.
    for a in soup.find_all("a", href=re.compile(r"^https?://app\.yomez\.com")):
        if a.decomposed:
            continue
        row = a.find_parent("div", class_="vc_row")
        if row and len(row.find_all("a")) == 1:
            row.decompose()
        elif a.find_parent("figure"):
            a.find_parent("figure").decompose()
        else:
            a.unwrap()  # keep any link text, drop the dead link


def clean(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Forms (Everest Forms) and their scripts/styles.
    for el in soup.select("div.everest-forms, form.everest-form"):
        el.decompose()
    # Search: header overlay, mobile search, and the JS trigger class.
    for el in soup.select("#fancy-search, form.mobile-search-form, form.search-form, .widget_search"):
        el.decompose()
    for el in soup.select(".hb-ajax-search"):
        el["class"] = [c for c in el["class"] if c != "hb-ajax-search"]
    # Comments.
    for el in soup.select("#respond, #comments, .comments-area, .comment-respond"):
        el.decompose()
    remove_app_links(soup)

    drop_asset = re.compile(r"everest-forms|wp-captcha|c4wp|recaptcha|intlTelInput|comment-reply")
    for el in soup.find_all(["script", "link"]):
        ref = el.get("src") or el.get("href") or ""
        if drop_asset.search(ref) or drop_asset.search(el.get("id") or ""):
            el.decompose()
            continue
        if el.name == "script" and not el.get("src") and el.string and re.search(
                r"C4WP|c4wp_|everest_forms|evf_", el.string):
            el.decompose()
            continue
        if el.name == "link":
            rel = " ".join(el.get("rel") or [])
            href = el.get("href") or ""
            if rel in ("EditURI", "pingback", "shortlink", "https://api.w.org/", "amphtml", "wlwmanifest") \
                    or (rel == "alternate" and ("/feed" in href or "oembed" in href or "wp-json" in href)):
                el.decompose()

    # Links that pointed at WP-only URLs.
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.endswith("?amp"):
            a["href"] = h = h[: -len("?amp")]
        if h.endswith("/page/1/"):  # WP redirected page 1 to the archive root
            a["href"] = h = h[: -len("page/1/")]
        if "/?p=1600" in h:
            a["href"] = ORIGIN + "/about-us/"
        if "/wp-login.php" in h or "/wp-admin" in h or h.rstrip("/").endswith("/feed"):
            a.unwrap()

    for c in soup.find_all(string=lambda s: isinstance(s, Comment) and "Simply Static" in s):
        c.extract()

    keep_abs = []  # canonical / og / JSON-LD keep absolute URLs
    for el in soup.select('link[rel=canonical], meta[property^="og:"], meta[name^="twitter:"], script[type="application/ld+json"]'):
        keep_abs.append(el)
        el["data-keep-abs"] = "1"

    out = str(soup)
    # Relativize everywhere except inside the kept-absolute tags.
    parts = re.split(r'(<[^>]*data-keep-abs="1"[^>]*>(?:.*?</script>)?)', out, flags=re.S)
    out = "".join(p if 'data-keep-abs="1"' in p else relativize(p) for p in parts)
    out = out.replace('"search_header":"1"', '"search_header":"0"')  # theme's search icon
    return out.replace(' data-keep-abs="1"', "")


def collect_assets(texts: list[str]) -> set[str]:
    refs = set()
    for t in texts:
        for m in ASSET_RE.finditer(t.replace("\\/", "/")):
            refs.add(m.group(0).split("?")[0].split("#")[0].lstrip("/"))
    # Follow CSS url()/@import references transitively.
    queue = [r for r in refs if r.endswith(".css")]
    while queue:
        css = queue.pop()
        f = SRC / css
        if not f.is_file():
            continue
        base = f.parent
        for m in CSS_URL_RE.finditer(f.read_text(encoding="utf-8", errors="replace")):
            u = (m.group(1) or m.group(2)).strip()
            if u.startswith(("data:", "http:", "https:", "//", "#")):
                if u.startswith(ORIGIN + "/"):
                    u = "/" + u[len(ORIGIN) + 1:]
                else:
                    continue
            u = u.split("?")[0].split("#")[0]
            target = (SRC / u.lstrip("/")) if u.startswith("/") else (base / u)
            try:
                rel = target.resolve().relative_to(SRC.resolve()).as_posix()
            except ValueError:
                continue
            if rel not in refs:
                refs.add(rel)
                if rel.endswith(".css"):
                    queue.append(rel)
    return refs


def write_extras(kept: list[str]) -> None:
    (OUT / "CNAME").write_text("yomez.com\n")
    (OUT / ".nojekyll").write_text("")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n")
    urls = "\n".join(
        f"  <url><loc>{ORIGIN}/{k + '/' if k else ''}</loc></url>"
        for k in sorted(kept) if "/page/" not in k)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "\n</urlset>\n")
    # Old URLs (Redirection plugin rules + WP old slugs) -> meta-refresh stubs.
    redirects = json.loads((ROOT / "scripts" / "redirects.json").read_text())
    for src, dest in redirects.items():
        stub = OUT / src.strip("/") / "index.html"
        if stub.exists():
            sys.exit(f"Redirect source {src} collides with a real page")
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(
            f'<!doctype html><meta charset="utf-8"><title>Redirecting…</title>'
            f'<link rel="canonical" href="{ORIGIN}{dest}">'
            f'<meta http-equiv="refresh" content="0; url={dest}">'
            f'<p><a href="{dest}">Continue</a></p>\n')


def make_404(home_html: str) -> str:
    """404 page: the home page chrome with a short message as the content."""
    soup = BeautifulSoup(home_html, "html.parser")
    main = soup.select_one("#main-content")
    if main is None:
        sys.exit("Home page has no #main-content; can't build 404.html")
    main.clear()
    main.append(BeautifulSoup(
        '<div class="container" style="padding:80px 0;text-align:center">'
        "<h1>Page not found</h1>"
        '<p>Sorry, that page doesn\'t exist. <a href="/">Go to the home page</a>.</p></div>',
        "html.parser"))
    if soup.title:
        soup.title.string = "Page not found – Yomez"
    for el in soup.select('link[rel=canonical], meta[property^="og:"]'):
        el.decompose()
    return str(soup)


def main() -> None:
    pages = load_pages()
    footer = footer_from(pages[FOOTER_DONOR])

    repaired = []
    for key, html in pages.items():
        if "wp-die-message" in html:
            pages[key] = repair(html, footer, key)
            repaired.append(key)

    # Prune junk pages that no non-junk page links to.
    junk = set(JUNK_CANDIDATES)
    linked = set()
    for key, html in pages.items():
        if key not in junk:
            linked |= links_in(html)
    dropped = sorted(k for k in junk if k in pages and k not in linked)
    kept_junk = sorted(k for k in junk if k in pages and k in linked)
    for k in dropped:
        del pages[k]

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    cleaned = {k: clean(v) for k, v in pages.items()}
    for key, html in cleaned.items():
        dest = OUT / key / "index.html" if key else OUT / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
    (OUT / "404.html").write_text(make_404(cleaned[""]), encoding="utf-8")

    assets = collect_assets(list(cleaned.values()))
    missing, too_big, total = [], [], 0
    for rel in sorted(assets):
        src = SRC / rel
        if not src.is_file():
            missing.append(rel)
            continue
        if src.stat().st_size > MAX_FILE_BYTES:
            too_big.append(rel)
            continue
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        total += src.stat().st_size

    write_extras(list(cleaned))

    print(f"pages written: {len(cleaned)} (+404)")
    print(f"repaired crashed pages: {len(repaired)}")
    print(f"dropped junk pages: {', '.join(dropped) or 'none'}")
    print(f"kept junk pages (linked from other pages): {', '.join(kept_junk) or 'none'}")
    print(f"assets copied: {len(assets) - len(missing) - len(too_big)} ({total / 1e6:.1f} MB)")
    if too_big:
        print("SKIPPED (over 95 MB):", *too_big, sep="\n  ")
    if missing:
        print(f"referenced but not in export: {len(missing)}", *missing[:40], sep="\n  ")


if __name__ == "__main__":
    main()

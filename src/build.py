"""Build the Molar Mass Pages static site.

Usage:  python src/build.py            (writes the site to ./dist)
Env:    SITE_URL  absolute base URL used for canonicals and the sitemap
"""
import csv
import html
import itertools
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

import chem

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SITE_URL = os.environ.get("SITE_URL", "https://hassanreschem-1616.github.io/molar-mass-pages").rstrip("/")

# Quality thresholds
MIN_WORDS = 180          # minimum words of visible text on a compound page
MIN_INTERNAL_LINKS = 6   # minimum internal links on a compound page
MAX_SIMILARITY = 0.55    # max Jaccard similarity (5-word shingles) between two compound pages
MAX_DESC_LEN = 160

env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True,
                  trim_blocks=True, lstrip_blocks=True)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_compounds():
    compounds = []
    with open(ROOT / "data" / "compounds.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a = chem.analyse(row["formula"])
            compounds.append({
                **row,
                "slug": "molar-mass-of-" + slugify(row["name"]),
                "pretty": chem.pretty(row["formula"]),
                "mm": a["molar_mass"],
                "rows": a["rows"],
                "atoms": a["atoms"],
                "symbols": {r["symbol"] for r in a["rows"]},
                "cat_slug": slugify(row["category"]),
                "lower_ok": not re.search(r"\([IVX]+\)", row["name"]),
            })
    slugs = [c["slug"] for c in compounds]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        sys.exit(f"Duplicate slugs in data: {dupes}")
    return compounds


def related_for(c, compounds, n=5):
    """Rank other compounds by shared elements, preferring the same category."""
    scored = []
    for o in compounds:
        if o is c:
            continue
        score = len(c["symbols"] & o["symbols"]) * 2 + (3 if o["category"] == c["category"] else 0)
        if score:
            scored.append((score, -abs(o["mm"] - c["mm"]), o))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [o for _, _, o in scored[:n]]


def faqs_for(c):
    mm = c["mm"]
    top = c["top"]
    name = c["name"].lower() if c["lower_ok"] else c["name"]
    return [
        {"q": f"How many grams are in 2.5 moles of {name}?",
         "a": f"Multiply moles by molar mass: 2.5 mol × {mm:.3f} g/mol = {2.5 * mm:.2f} g of {c['formula']}."},
        {"q": f"How many moles are in 100 g of {name}?",
         "a": f"Divide mass by molar mass: 100 g ÷ {mm:.3f} g/mol = {100 / mm:.4f} mol of {c['formula']}."},
        {"q": f"How much {top['name'].lower()} is in 50 g of {name}?",
         "a": f"{top['name']} is {top['percent']:.2f}% of the mass, so 50 g × {top['percent'] / 100:.4f} "
              f"= {50 * top['percent'] / 100:.2f} g of {top['name'].lower()}."},
    ]


def schema_breadcrumbs(crumbs):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": c["name"],
                                 "item": f"{SITE_URL}/{c['href']}"} for i, c in enumerate(crumbs)]}


def write(path: str, template: str, **ctx):
    """path is like 'molar-mass-of-water/' or '' for the home page."""
    depth = path.count("/")
    out = DIST / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    page = env.get_template(template).render(root="../" * depth, site_url=SITE_URL,
                                             path="/" + path, **ctx)
    out.write_text(page, encoding="utf-8")
    return {"path": path, "html": page, "title": ctx["title"], "description": ctx["description"],
            "kind": template}


def build():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copytree(ROOT / "static", DIST / "static")

    compounds = load_compounds()
    pages = []
    home = {"name": "Home", "href": ""}

    categories = {}
    for c in compounds:
        categories.setdefault(c["category"], []).append(c)
    by_element = {}
    for c in compounds:
        for r in c["rows"]:
            by_element.setdefault(r["symbol"], []).append((c, r["percent"]))

    # Compound pages
    for c in compounds:
        c["top"] = max(c["rows"], key=lambda r: r["percent"])
        c["rows_by_pct"] = sorted(c["rows"], key=lambda r: r["percent"], reverse=True)
        c["equation"] = " + ".join(f"{r['count']} × {r['atomic_mass']:.3f}" for r in c["rows"])
        c["related"] = related_for(c, compounds)
        c["faqs"] = faqs_for(c)
        crumbs = [home, {"name": c["category"], "href": f"category/{c['cat_slug']}/"},
                  {"name": c["name"], "href": f"{c['slug']}/"}]
        desc = (f"{c['name']} ({c['formula']}) has a molar mass of {c['mm']:.3f} g/mol. "
                f"See the step-by-step calculation and mass percent of each element.")
        faq_schema = {"@context": "https://schema.org", "@type": "FAQPage",
                      "mainEntity": [{"@type": "Question", "name": q["q"],
                                      "acceptedAnswer": {"@type": "Answer", "text": q["a"]}}
                                     for q in c["faqs"]]}
        pages.append(write(f"{c['slug']}/", "compound.html", c=c, crumbs=crumbs,
                           title=f"Molar Mass of {c['name']} ({c['formula']}) – {c['mm']:.2f} g/mol",
                           description=desc, schema=[schema_breadcrumbs(crumbs), faq_schema]))

    # Category hubs
    cat_links = [{"name": k, "path": f"category/{slugify(k)}/"} for k in sorted(categories)]
    for cat, items in sorted(categories.items()):
        slug = slugify(cat)
        crumbs = [home, {"name": cat, "href": f"category/{slug}/"}]
        lo, hi = min(items, key=lambda c: c["mm"]), max(items, key=lambda c: c["mm"])
        intro = (f"{len(items)} {cat.lower()} with calculated molar masses, from {lo['name']} "
                 f"({lo['mm']:.2f} g/mol) to {hi['name']} ({hi['mm']:.2f} g/mol).")
        pages.append(write(f"category/{slug}/", "hub.html", crumbs=crumbs, heading=f"Molar masses of {cat.lower()}",
                           intro=intro, items=sorted(items, key=lambda c: c["mm"]), show_pct=None,
                           siblings=[s for s in cat_links if s["name"] != cat], siblings_title="Other categories",
                           title=f"Molar Mass of {cat}: {len(items)} Compounds with Calculations",
                           description=f"Molar masses of {len(items)} {cat.lower()}, each with a step-by-step "
                                       f"calculation and mass percent composition.",
                           schema=[schema_breadcrumbs(crumbs)]))

    # Element hubs
    el_links = [{"name": chem.ELEMENTS[s]["name"], "path": f"element/{s.lower()}/"} for s in sorted(by_element)]
    for sym, pairs in sorted(by_element.items()):
        el = chem.ELEMENTS[sym]
        crumbs = [home, {"name": f"Compounds with {el['name'].lower()}", "href": f"element/{sym.lower()}/"}]
        items = [{**c, "pct": p} for c, p in sorted(pairs, key=lambda t: t[1], reverse=True)]
        richest = items[0]
        intro = (f"{len(items)} compound{'s' if len(items) > 1 else ''} containing {el['name'].lower()} ({sym}, "
                 f"atomic mass {el['mass']} g/mol), ranked by {el['name'].lower()} content. "
                 f"{richest['name']} has the highest share at {richest['pct']:.1f}% by mass.")
        pages.append(write(f"element/{sym.lower()}/", "hub.html", crumbs=crumbs,
                           heading=f"Compounds containing {el['name'].lower()} ({sym})", intro=intro,
                           items=items, show_pct=el["name"], siblings=[s for s in el_links if s["name"] != el["name"]],
                           siblings_title="Other elements",
                           title=f"{el['name']} ({sym}) Compounds: Molar Mass and % {el['name']} by Mass",
                           description=f"{len(items)} compounds containing {el['name'].lower()}, with molar "
                                       f"mass and percent {el['name'].lower()} by mass for each.",
                           schema=[schema_breadcrumbs(crumbs)]))

    # Home page
    pages.append(write("", "hub.html", crumbs=None, heading="Molar mass of common compounds",
                       intro=f"Step-by-step molar mass calculations for {len(compounds)} compounds, "
                             f"with mass percent composition and worked examples.",
                       items=sorted(compounds, key=lambda c: c["name"]), show_pct=None,
                       siblings=cat_links + el_links, siblings_title="Browse by category or element",
                       title="Molar Mass Calculations for Common Compounds (g/mol)",
                       description=f"Molar masses of {len(compounds)} common compounds with step-by-step "
                                   f"calculations, mass percent composition and worked examples.",
                       schema=[{"@context": "https://schema.org", "@type": "WebSite",
                                "name": "Molar Mass Pages", "url": SITE_URL + "/"}]))

    # Sitemap and robots
    today = date.today().isoformat()
    urls = "\n".join(f"  <url><loc>{SITE_URL}/{p['path']}</loc><lastmod>{today}</lastmod></url>" for p in pages)
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n</urlset>\n", encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")
    (DIST / ".nojekyll").write_text("")
    return pages


# ---------------------------------------------------------------- quality gate

def visible_text(page_html: str) -> str:
    body = page_html.split("<main>", 1)[1].split("</main>", 1)[0]
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))).strip()


def internal_links(page_html: str, page_path: str):
    """Resolve relative hrefs inside <main> to site paths like 'element/na/'."""
    body = page_html.split("<main>", 1)[1].split("</main>", 1)[0]
    base = page_path.split("/")[:-1]
    found = set()
    for href in re.findall(r'href="([^"#]+)"', body):
        if href.startswith("http"):
            continue
        parts = base[:]
        for seg in href.split("/"):
            if seg == "..":
                parts = parts[:-1]
            elif seg:
                parts.append(seg)
        found.add("/".join(parts) + "/" if parts else "")
    return found


def shingles(text: str, k=5):
    words = re.findall(r"[a-z0-9.%]+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def quality_report(pages):
    errors, notes = [], []
    titles, descs = {}, {}
    for p in pages:
        titles.setdefault(p["title"], []).append(p["path"])
        descs.setdefault(p["description"], []).append(p["path"])
        if len(p["description"]) > MAX_DESC_LEN:
            errors.append(f"Description too long ({len(p['description'])} chars): /{p['path']}")
    errors += [f"Duplicate title on {v}" for v in titles.values() if len(v) > 1]
    errors += [f"Duplicate description on {v}" for v in descs.values() if len(v) > 1]

    inbound = {p["path"]: 0 for p in pages}
    compound_pages = [p for p in pages if p["kind"] == "compound.html"]
    for p in pages:
        links = internal_links(p["html"], p["path"])
        for target in links:
            if target in inbound and target != p["path"]:
                inbound[target] += 1
        if p["kind"] == "compound.html":
            words = len(visible_text(p["html"]).split())
            if words < MIN_WORDS:
                errors.append(f"Thin page ({words} words): /{p['path']}")
            if len(links) < MIN_INTERNAL_LINKS:
                errors.append(f"Too few internal links ({len(links)}): /{p['path']}")
    errors += [f"Orphan page (no inbound links): /{path}" for path, n in inbound.items() if n == 0 and path]

    sh = {p["path"]: shingles(visible_text(p["html"])) for p in compound_pages}
    worst = (0.0, None, None)
    for a, b in itertools.combinations(sh, 2):
        sim = len(sh[a] & sh[b]) / len(sh[a] | sh[b])
        if sim > worst[0]:
            worst = (sim, a, b)
        if sim > MAX_SIMILARITY:
            errors.append(f"Near-duplicate pages ({sim:.2f}): /{a} and /{b}")

    words = [len(visible_text(p["html"]).split()) for p in compound_pages]
    notes.append(f"Pages built: {len(pages)} ({len(compound_pages)} compound pages, "
                 f"{len(pages) - len(compound_pages)} hub pages)")
    notes.append(f"Compound page length: {min(words)}–{max(words)} words")
    notes.append(f"Most similar pair: {worst[0]:.2f} (/{worst[1]} vs /{worst[2]}), limit {MAX_SIMILARITY}")
    notes.append(f"Fewest inbound links to any page: {min(n for k, n in inbound.items() if k)}")
    return errors, notes


if __name__ == "__main__":
    built = build()
    errs, info = quality_report(built)
    report = ["# Build quality report", ""] + [f"- {n}" for n in info] + ["", "## Errors", ""]
    report += [f"- {e}" for e in errs] or ["- None"]
    (ROOT / "quality-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(info))
    if errs:
        print("\nQUALITY GATE FAILED:\n" + "\n".join(errs))
        sys.exit(1)
    print("\nQuality gate passed. Site written to dist/")

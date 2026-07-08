#!/usr/bin/env python3
"""Render a screenshot-content-ingest JSON output's `digest` block as a newsletter-style HTML page.

Unlike generate_dashboard.py (one card per entry, neutral/evidence-only), this
renders the optional editorial synthesis layer: entries grouped into themed
sections, each with a one-sentence takeaway. Coverage is complete -- every
entry appears via exactly one finding -- but only `tier: "featured"` findings
get the full card treatment; `tier: "standard"` findings render as compact
rows so a large batch stays scannable. See references/output-schema.md for
the `digest` schema and SKILL.md step 9 for how it's generated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


def slugify(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def load_data(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "entries" not in data:
        raise ValueError("Input JSON must be a screenshot-content-ingest output object with an 'entries' array.")
    return data


def entries_by_id(data: dict) -> dict[str, dict]:
    return {entry.get("id"): entry for entry in data.get("entries") or []}


def finding_image(entry: dict | None) -> str | None:
    if not entry:
        return None
    files = ((entry.get("consolidation") or {}).get("source_images")) or []
    return files[0] if files else None


def finding_files(entry: dict | None) -> list[str]:
    if not entry:
        return []
    return ((entry.get("consolidation") or {}).get("source_images")) or []


def status_class(status: str | None) -> str:
    return "warn" if status == "needs-review" else "good"


def render_featured(finding: dict, entry: dict | None) -> str:
    image = finding_image(entry)
    thumb = (
        f'<img src="{esc(image)}" alt="{esc(finding.get("headline", ""))}" loading="lazy">'
        if image
        else '<div class="placeholder"></div>'
    )
    badge = finding.get("badge")
    source_app = ((entry or {}).get("source") or {}).get("app")
    status = finding.get("status") or "usable"
    names = finding.get("names") or []
    names_html = "".join(f"<span>{esc(name)}</span>" for name in names)
    takeaway = finding.get("takeaway")
    summary = finding.get("summary") or ((entry or {}).get("content") or {}).get("summary") or ""
    files = finding_files(entry)
    files_html = "".join(f'<a href="{esc(f)}" target="_blank">{esc(Path(f).name)}</a>' for f in files)
    eyebrow_bits = [b for b in [badge, source_app, status] if b]
    eyebrow_html = "".join(
        f"<span>{esc(bit)}</span>" if i else f"<span>{esc(bit)}</span>" for i, bit in enumerate(eyebrow_bits)
    )
    return f"""
    <article class="card">
      <div class="shot">{thumb}</div>
      <div class="copy">
        <div class="eyebrow">{eyebrow_html}</div>
        <h3>{esc(finding.get("headline") or (entry or {}).get("title") or "(untitled)")}</h3>
        <p>{esc(summary)}</p>
        {f'<div class="takeaway"><strong>Takeaway:</strong> {esc(takeaway)}</div>' if takeaway else ""}
        <div class="names">{names_html}</div>
        <details>
          <summary>Source: {esc(finding.get("entry_id"))}</summary>
          <div class="files">{files_html}</div>
        </details>
      </div>
    </article>"""


def render_standard(finding: dict, entry: dict | None) -> str:
    cls = status_class(finding.get("status"))
    headline = finding.get("headline") or (entry or {}).get("title") or "(untitled)"
    takeaway = finding.get("takeaway") or ""
    return f"""
    <div class="compact-row">
      <span class="dot {cls}"></span>
      <span class="compact-headline">{esc(headline)}</span>
      <span class="compact-takeaway">{esc(takeaway)}</span>
    </div>"""


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__PAGE_TITLE__</title>
  <style>
    :root {
      --bg: #f4f5f7; --paper: #ffffff; --ink: #181a1f; --muted: #626a76;
      --line: #d7dde5; --green: #0a736a; --blue: #244f98; --amber: #9c5b00;
      --soft: #edf2f5; --shadow: 0 12px 28px rgba(17, 24, 39, .08);
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    a { color: var(--blue); }
    .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 22px 54px; }
    header { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(280px, .75fr); gap: 22px; align-items: stretch; margin-bottom: 22px; }
    .hero, .brief, section { background: var(--paper); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); }
    .hero { padding: 28px; }
    .kicker { color: var(--green); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 10px; }
    h1 { margin: 0; font-size: 38px; line-height: 1.02; letter-spacing: 0; }
    .hero p { max-width: 760px; color: var(--muted); font-size: 17px; margin: 14px 0 0; }
    .brief { padding: 22px; }
    .brief h2, .section-head h2 { margin: 0; font-size: 20px; letter-spacing: 0; }
    .brief ul { margin: 12px 0 0; padding-left: 20px; }
    .brief li { margin: 8px 0; }
    nav { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 26px; }
    nav a { text-decoration: none; color: var(--ink); border: 1px solid var(--line); border-radius: 999px; background: var(--paper); padding: 7px 11px; font-size: 13px; font-weight: 650; }
    section { padding: 20px; margin: 18px 0; }
    .section-head { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; border-bottom: 1px solid var(--line); padding-bottom: 12px; margin-bottom: 14px; }
    .section-head p { margin: 0; color: var(--muted); font-size: 13px; }
    .cards { display: grid; gap: 14px; }
    .card { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 16px; padding: 14px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
    .shot img, .placeholder { width: 100%; aspect-ratio: 9 / 16; border-radius: 6px; border: 1px solid var(--line); background: var(--soft); object-fit: cover; object-position: top; display: block; }
    h3 { margin: 6px 0 8px; font-size: 20px; line-height: 1.2; }
    .copy p { margin: 0 0 10px; color: #323740; }
    .eyebrow, .names { display: flex; flex-wrap: wrap; gap: 6px; }
    .eyebrow span, .names span { border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; color: var(--muted); background: #fff; font-size: 12px; white-space: nowrap; }
    .eyebrow span:first-child { color: var(--green); border-color: rgba(10, 115, 106, .28); background: rgba(10, 115, 106, .07); }
    .takeaway { border-left: 3px solid var(--green); padding: 8px 10px; margin: 10px 0; background: rgba(10, 115, 106, .06); border-radius: 0 6px 6px 0; }
    details { margin-top: 10px; color: var(--muted); }
    summary { cursor: pointer; font-weight: 700; color: var(--blue); }
    .files { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .files a { border: 1px solid var(--line); border-radius: 6px; padding: 3px 7px; text-decoration: none; font-size: 12px; background: #fff; }
    .standard-list { margin-top: 16px; border-top: 1px dashed var(--line); padding-top: 12px; }
    .standard-head { color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 8px; }
    .compact-row { display: flex; align-items: baseline; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--soft); font-size: 13px; }
    .dot { width: 8px; height: 8px; border-radius: 999px; flex: none; background: var(--muted); }
    .dot.good { background: var(--green); }
    .dot.warn { background: var(--amber); }
    .compact-headline { font-weight: 650; white-space: nowrap; }
    .compact-takeaway { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .note { margin-top: 24px; color: var(--muted); font-size: 13px; }
    @media (max-width: 860px) {
      header { grid-template-columns: 1fr; }
      h1 { font-size: 32px; }
      .card { grid-template-columns: 110px minmax(0, 1fr); }
    }
    @media (max-width: 620px) {
      .wrap { padding: 18px 12px 40px; }
      .card { grid-template-columns: 1fr; }
      .shot img, .placeholder { max-height: 360px; object-fit: contain; }
      .section-head { display: block; }
      .compact-row { flex-wrap: wrap; }
      .compact-takeaway { white-space: normal; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="hero">
        <div class="kicker">__KICKER__</div>
        <h1>__MAIN_TITLE__</h1>
        <p>__MAIN_SUBTITLE__</p>
      </div>
      <aside class="brief">
        <h2>Editor's shortlist</h2>
        <ul>__SHORTLIST__</ul>
      </aside>
    </header>
    <nav>__NAV__</nav>
    __SECTIONS__
    <div class="note">__NOTE__</div>
  </div>
</body>
</html>
"""


def render(data: dict, title: str) -> str:
    digest = data.get("digest") or {}
    if not digest.get("generated"):
        raise ValueError("data['digest']['generated'] is not true -- run the digest pass (SKILL.md step 9) first.")

    lookup = entries_by_id(data)
    sections = digest.get("sections") or []
    shortlist = digest.get("shortlist") or []

    shortlist_html = "".join(f"<li>{esc(item)}</li>" for item in shortlist) or "<li>No shortlist items.</li>"

    nav_html = "".join(
        f'<a href="#{esc(slugify(section.get("title", section.get("id", ""))))}">{esc(section.get("title", "Untitled section"))}</a>'
        for section in sections
    )

    total_findings = sum(len(section.get("findings") or []) for section in sections)
    total_entries = len(lookup)

    section_blocks = []
    for section in sections:
        findings = sorted(section.get("findings") or [], key=lambda f: f.get("rank") if f.get("rank") is not None else 999)
        featured = [f for f in findings if f.get("tier") == "featured"]
        standard = [f for f in findings if f.get("tier") != "featured"]

        featured_html = "".join(render_featured(f, lookup.get(f.get("entry_id"))) for f in featured)
        standard_html = "".join(render_standard(f, lookup.get(f.get("entry_id"))) for f in standard)
        standard_block = (
            f'<div class="standard-list"><div class="standard-head">Also in this section ({len(standard)})</div>{standard_html}</div>'
            if standard
            else ""
        )

        slug = slugify(section.get("title", section.get("id", "")))
        section_blocks.append(
            f"""
            <section id="{esc(slug)}">
              <div class="section-head">
                <h2>{esc(section.get("title", "Untitled section"))}</h2>
                <p>{len(findings)} finding(s) &middot; {len(featured)} featured</p>
              </div>
              <div class="cards">{featured_html}</div>
              {standard_block}
            </section>"""
        )

    html = TEMPLATE
    html = html.replace("__PAGE_TITLE__", esc(title))
    html = html.replace("__KICKER__", "Screenshot Digest")
    html = html.replace("__MAIN_TITLE__", esc(title))
    html = html.replace(
        "__MAIN_SUBTITLE__",
        "Every screenshot is covered; the strongest findings are featured, the rest listed for a quick scan.",
    )
    html = html.replace("__SHORTLIST__", shortlist_html)
    html = html.replace("__NAV__", nav_html)
    html = html.replace("__SECTIONS__", "".join(section_blocks))
    generated_at = digest.get("generated_at") or "unknown time"
    html = html.replace(
        "__NOTE__",
        esc(f"Generated {generated_at} · {total_findings} findings across {len(sections)} section(s), covering {total_entries} entries."),
    )
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", help="Path to screenshot-content-ingest.json with a populated 'digest' block")
    parser.add_argument("-o", "--output", default="screenshot-content-ingest-digest.html", help="Output HTML file path")
    parser.add_argument("--title", default="Screenshot Intelligence Digest", help="Page title / hero heading")
    args = parser.parse_args()

    data = load_data(Path(args.input_json))
    html = render(data, args.title)

    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    digest = data.get("digest") or {}
    finding_count = sum(len(s.get("findings") or []) for s in digest.get("sections") or [])
    print(f"Wrote {out_path} ({finding_count} findings)")


if __name__ == "__main__":
    main()

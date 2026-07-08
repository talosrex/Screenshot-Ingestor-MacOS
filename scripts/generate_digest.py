#!/usr/bin/env python3
"""Render a screenshot-content-ingest JSON output's `digest` block as a newsletter-style HTML page.

Unlike generate_dashboard.py (one card per entry, neutral/evidence-only), this
renders the optional editorial synthesis layer: entries grouped into themed
sections, each with a one-sentence takeaway. Coverage is complete -- every
entry appears via exactly one finding -- but only `tier: "featured"` findings
get the full card treatment; `tier: "standard"` findings render as compact
rows so a large batch stays scannable. Includes the same sidebar
search/filter/sort pattern as generate_dashboard.py, applied to findings
instead of raw entries. See references/output-schema.md for the `digest`
schema and SKILL.md step 9 for how it's generated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_data(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "entries" not in data:
        raise ValueError("Input JSON must be a screenshot-content-ingest output object with an 'entries' array.")
    return data


def entries_by_id(data: dict) -> dict[str, dict]:
    return {entry.get("id"): entry for entry in data.get("entries") or []}


def flatten_findings(data: dict) -> list[dict]:
    digest = data.get("digest") or {}
    if not digest.get("generated"):
        raise ValueError("data['digest']['generated'] is not true -- run the digest pass (SKILL.md step 9) first.")

    lookup = entries_by_id(data)
    rows: list[dict] = []
    for section_order, section in enumerate(digest.get("sections") or []):
        section_title = section.get("title") or section.get("id") or "Untitled section"
        section_id = section.get("id") or section_title
        for finding in section.get("findings") or []:
            entry = lookup.get(finding.get("entry_id")) or {}
            source = entry.get("source") or {}
            content = entry.get("content") or {}
            files = ((entry.get("consolidation") or {}).get("source_images")) or []
            rows.append(
                {
                    "entry_id": finding.get("entry_id"),
                    "section_title": section_title,
                    "section_id": section_id,
                    "section_order": section_order,
                    "tier": finding.get("tier") or "standard",
                    "headline": finding.get("headline") or entry.get("title") or "(untitled)",
                    "takeaway": finding.get("takeaway") or "",
                    "summary": finding.get("summary") or content.get("summary") or "",
                    "badge": finding.get("badge") or "",
                    "names": finding.get("names") or [],
                    "status": finding.get("status") or "usable",
                    "rank": finding.get("rank"),
                    "source_app": source.get("app") or "unknown",
                    "image": files[0] if files else None,
                    "files": files,
                    "visible_text": content.get("visible_text") or "",
                }
            )
    return rows


def build_stats(rows: list[dict], section_count: int) -> dict:
    by_section: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for row in rows:
        by_section[row["section_title"]] = by_section.get(row["section_title"], 0) + 1
        by_source[row["source_app"]] = by_source.get(row["source_app"], 0) + 1
    return {
        "total": len(rows),
        "featured": sum(1 for r in rows if r["tier"] == "featured"),
        "needsReview": sum(1 for r in rows if r["status"] == "needs-review"),
        "sections": section_count,
        "bySection": sorted(by_section.items(), key=lambda kv: kv[1], reverse=True),
        "bySourceApp": sorted(by_source.items(), key=lambda kv: kv[1], reverse=True),
    }


def safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</script", "<\\/script")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__PAGE_TITLE__</title>
  <script>
    (function () {
      try {
        var saved = localStorage.getItem("screenshot-digest-theme");
        var theme = saved || ((window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light");
        document.documentElement.setAttribute("data-theme", theme);
      } catch (e) {}
    })();
  </script>
  <style>
    /*
      Paired background/foreground tokens (design-tokens.css convention):
      every --color-X background has a matching --color-on-X foreground,
      always at full opacity. See scripts/../references for the source
      guideline; verified with the project's validate-contrast.js.
      --color-on-page* and --color-on-surface* happen to share values in
      this palette (both resolve against light/near-white or dark/near-black
      surfaces), but are kept as separate named pairs for clarity.
    */
    :root {
      --color-page: #EAECF0;
      --color-on-page: #000000;
      --color-on-page-muted: #233D4D;
      --color-surface: #ffffff;
      --color-on-surface: #000000;
      --color-on-surface-muted: #233D4D;
      --color-accent-strong: #FE7F2D;
      --color-on-accent-strong: #000000;
      --color-chip: #233D4D;
      --color-on-chip: #EAECF0;
      --line: #EAECF0;
      --shadow: 0 10px 24px rgba(0, 0, 0, .08);
      --focus-ring: #DA6D27;       /* darkened accent: raw #FE7F2D fails 3:1 as a thin foreground/border on light surfaces */
      --overlay-focus: rgba(254, 127, 45, .18); /* decorative glow only; --focus-ring border carries the a11y contrast */
    }
    :root[data-theme="dark"] {
      --color-page: #000000;
      --color-on-page: #EAECF0;
      --color-on-page-muted: #A9BCC5;
      --color-surface: #233D4D;
      --color-on-surface: #EAECF0;
      --color-on-surface-muted: #A9BCC5;
      --color-accent-strong: #FE7F2D;
      --color-on-accent-strong: #000000;
      --color-chip: #000000;
      --color-on-chip: #EAECF0;
      --line: rgba(234, 236, 240, .14);
      --shadow: 0 10px 24px rgba(0, 0, 0, .55);
      --focus-ring: #DA6D27;
      --overlay-focus: rgba(254, 127, 45, .3);
    }
    /*
      Dark mode only: flip which pairing backs "container" vs "raised"
      elements. --color-page/on-page is the darker pairing (already used
      for body/main); here the sidebar itself also becomes page-colored
      ("the background"), while dropdowns and tag chips move to the
      lighter --color-surface/on-surface pairing that cards already use,
      so raised elements read as lighter than the background they sit on.
      .stat/.track move with the sidebar so they stay visible against it.
    */
    :root[data-theme="dark"] aside { background: var(--color-page); color: var(--color-on-page); }
    :root[data-theme="dark"] .stat { background: var(--color-surface); }
    :root[data-theme="dark"] .stat strong { color: var(--color-on-surface); }
    :root[data-theme="dark"] input,
    :root[data-theme="dark"] select { background: var(--color-surface); color: var(--color-on-surface); }
    :root[data-theme="dark"] .track { background: var(--color-surface); }
    :root[data-theme="dark"] .eyebrow span,
    :root[data-theme="dark"] .names span { background: var(--color-surface); }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--color-page);
      color: var(--color-on-page);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      transition: background-color .15s ease, color .15s ease;
    }
    .theme-toggle {
      position: sticky;
      top: 0;
      z-index: 1;
      width: 100%;
      margin-bottom: 16px;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--color-surface);
      color: var(--color-on-surface);
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: background-color .15s ease, color .15s ease, border-color .15s ease;
    }
    .theme-toggle:hover { border-color: var(--focus-ring); }
    a { color: var(--color-on-surface-muted); }
    .layout {
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }
    aside {
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      padding: 20px;
      background: var(--color-surface);
      color: var(--color-on-surface);
      border-right: 1px solid var(--line);
    }
    main { padding: 24px; min-width: 0; }
    h1 { margin: 0 0 4px; font-size: 22px; letter-spacing: 0; color: var(--color-on-surface); }
    .kicker {
      display: inline-block; background: var(--color-accent-strong); color: var(--color-on-accent-strong);
      font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em;
      margin-bottom: 8px; padding: 3px 8px; border-radius: 999px;
    }
    .muted { color: var(--color-on-surface-muted); font-size: 12px; }
    .stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 16px 0; }
    .stat { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: var(--color-page); }
    .stat strong { display: block; font-size: 22px; line-height: 1.1; color: var(--color-on-page); }
    label { display: block; margin: 12px 0 5px; font-size: 12px; color: var(--color-on-surface-muted); font-weight: 700; }
    input, select {
      width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px;
      background: var(--color-page); color: var(--color-on-page); font: inherit;
    }
    input:focus, select:focus { outline: 0; border-color: var(--focus-ring); box-shadow: 0 0 0 3px var(--overlay-focus); }
    h2 { margin: 20px 0 10px; color: var(--color-on-surface-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    .shortlist { margin: 0; padding-left: 18px; }
    .shortlist li { margin: 6px 0; color: var(--color-on-surface); font-size: 13px; }
    .bar-list { display: grid; gap: 8px; }
    .bar-row { display: grid; grid-template-columns: 1fr 30px; gap: 8px; color: var(--color-on-surface-muted); font-size: 12px; align-items: center; }
    .track { height: 7px; border-radius: 999px; background: var(--color-page); overflow: hidden; margin-top: 3px; }
    .fill { height: 100%; width: var(--w); background: var(--color-on-surface-muted); }
    .section-block { margin: 0 0 26px; }
    .section-head {
      display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
      border-bottom: 2px solid var(--color-on-page); padding-bottom: 8px; margin-bottom: 14px;
    }
    .section-head h3 { margin: 0; font-size: 19px; }
    .section-head span { color: var(--color-on-page-muted); font-size: 12px; white-space: nowrap; }
    .cards { display: grid; gap: 14px; }
    .card {
      display: grid; grid-template-columns: minmax(150px, 210px) minmax(0, 1fr); gap: 16px;
      padding: 14px; border: 1px solid var(--line); border-radius: 8px;
      background: var(--color-surface); color: var(--color-on-surface); box-shadow: var(--shadow);
    }
    .shot img, .placeholder {
      width: 100%; max-height: 430px; aspect-ratio: 9/16; border-radius: 6px; border: 1px solid var(--line);
      background: var(--color-page); object-fit: cover; object-position: top; display: block;
    }
    h3.headline { margin: 4px 0 8px; font-size: 19px; line-height: 1.25; color: var(--color-on-surface); }
    .copy p { margin: 0 0 10px; color: var(--color-on-surface); }
    .eyebrow, .names { display: flex; flex-wrap: wrap; gap: 6px; }
    .eyebrow span, .names span {
      border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; color: var(--color-on-surface-muted);
      background: var(--color-page); font-size: 11px; white-space: nowrap;
    }
    .eyebrow span.status-warn { background: var(--color-accent-strong); color: var(--color-on-accent-strong); border-color: var(--color-accent-strong); }
    .eyebrow span.status-good { background: var(--color-chip); color: var(--color-on-chip); border-color: var(--color-chip); }
    .takeaway {
      padding: 10px 12px; margin: 10px 0; border-radius: 6px;
      background: var(--color-accent-strong); color: var(--color-on-accent-strong);
    }
    details { margin-top: 10px; color: var(--color-on-surface-muted); }
    summary { cursor: pointer; font-weight: 700; color: var(--color-on-surface-muted); }
    .files { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .files a { border: 1px solid var(--line); border-radius: 6px; padding: 3px 7px; text-decoration: none; font-size: 12px; background: var(--color-page); }
    .compact-row { display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-bottom: 1px solid var(--line); font-size: 13px; }
    .compact-row:last-child { border-bottom: none; }
    .mini-badge {
      flex: none; font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .03em;
      padding: 2px 7px; border-radius: 999px;
    }
    .mini-badge.good { background: var(--color-chip); color: var(--color-on-chip); }
    .mini-badge.warn { background: var(--color-accent-strong); color: var(--color-on-accent-strong); }
    .compact-headline { font-weight: 650; white-space: nowrap; }
    .compact-takeaway { color: var(--color-on-page-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .empty { padding: 28px; text-align: center; border: 1px dashed var(--line); border-radius: 8px; background: var(--color-surface); color: var(--color-on-surface-muted); }
    @media (max-width: 960px) {
      .layout { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      main { padding: 16px; }
      .card { grid-template-columns: 120px minmax(0, 1fr); }
    }
    @media (max-width: 640px) {
      .card { grid-template-columns: 1fr; }
      .compact-row { flex-wrap: wrap; }
      .compact-takeaway { white-space: normal; }
    }
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <button id="themeToggle" class="theme-toggle" type="button">Dark mode</button>
      <div class="kicker">Screenshot Digest</div>
      <h1>__MAIN_TITLE__</h1>
      <div class="muted">Every screenshot covered; strongest findings featured.</div>
      <div class="stats">
        <div class="stat"><strong id="total">0</strong><span>findings</span></div>
        <div class="stat"><strong id="shown">0</strong><span>shown</span></div>
        <div class="stat"><strong id="featured">0</strong><span>featured</span></div>
        <div class="stat"><strong id="needs">0</strong><span>need review</span></div>
      </div>
      <label for="search">Search</label>
      <input id="search" type="search" placeholder="headline, takeaway, source, tag">
      <label for="section">Section</label>
      <select id="section"></select>
      <label for="status">Status</label>
      <select id="status">
        <option value="all">All statuses</option>
        <option value="usable">Usable</option>
        <option value="needs-review">Needs review</option>
      </select>
      <label for="tier">Tier</label>
      <select id="tier">
        <option value="all">Featured + standard</option>
        <option value="featured">Featured only</option>
        <option value="standard">Standard only</option>
      </select>
      <label for="sort">Sort</label>
      <select id="sort">
        <option value="section">Section order</option>
        <option value="needs-review">Needs review first</option>
        <option value="az">Alphabetical</option>
      </select>
      <h2>Editor's shortlist</h2>
      <ul class="shortlist" id="shortlist"></ul>
      <h2>By section</h2>
      <div id="sectionBars" class="bar-list"></div>
      <h2>By source</h2>
      <div id="sourceBars" class="bar-list"></div>
    </aside>
    <main>
      <div id="sections"></div>
    </main>
  </div>
  <script>
    const FINDINGS = __FINDINGS__;
    const STATS = __STATS__;
    const SHORTLIST = __SHORTLIST__;
    const state = { search: "", section: "all", status: "all", tier: "all", sort: "section" };
    const $ = id => document.getElementById(id);
    const els = ["search","section","status","tier","sort"].reduce((a, id) => (a[id] = $(id), a), {});

    function esc(value) {
      return String(value ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
    }
    function options(el, values, label) {
      el.innerHTML = `<option value="all">All ${label}</option>` + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    }
    function bars(el, rows) {
      const max = rows.length ? rows[0][1] : 1;
      el.innerHTML = rows.slice(0, 10).map(([label, count]) => {
        const w = Math.max(4, Math.round(count / max * 100));
        return `<div class="bar-row"><div><div>${esc(label)}</div><div class="track"><div class="fill" style="--w:${w}%"></div></div></div><strong>${count}</strong></div>`;
      }).join("");
    }
    function applyTheme(theme) {
      document.documentElement.setAttribute("data-theme", theme);
      try { localStorage.setItem("screenshot-digest-theme", theme); } catch (e) {}
      $("themeToggle").textContent = theme === "dark" ? "Light mode" : "Dark mode";
    }
    function initTheme() {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      applyTheme(current);
      $("themeToggle").addEventListener("click", () => {
        const now = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        applyTheme(now);
      });
    }
    function init() {
      initTheme();
      options(els.section, [...new Set(FINDINGS.map(f => f.section_title))], "sections");
      $("total").textContent = STATS.total;
      $("featured").textContent = STATS.featured;
      $("needs").textContent = STATS.needsReview;
      $("shortlist").innerHTML = SHORTLIST.map(item => `<li>${esc(item)}</li>`).join("") || "<li>No shortlist items.</li>";
      bars($("sectionBars"), STATS.bySection);
      bars($("sourceBars"), STATS.bySourceApp);
      Object.entries(els).forEach(([key, input]) => input.addEventListener("input", () => {
        state[key] = input.value;
        render();
      }));
      render();
    }
    function hay(f) {
      return [f.headline, f.takeaway, f.summary, f.source_app, f.visible_text, (f.names||[]).join(" ")].join(" ").toLowerCase();
    }
    function filtered() {
      const q = state.search.trim().toLowerCase();
      let rows = FINDINGS.filter(f =>
        (!q || hay(f).includes(q)) &&
        (state.section === "all" || f.section_title === state.section) &&
        (state.status === "all" || f.status === state.status) &&
        (state.tier === "all" || f.tier === state.tier)
      );
      if (state.sort === "needs-review") {
        rows.sort((a, b) => {
          const ar = a.status === "needs-review" ? 0 : 1;
          const br = b.status === "needs-review" ? 0 : 1;
          return ar - br || a.section_order - b.section_order || (a.rank ?? 999) - (b.rank ?? 999);
        });
      } else if (state.sort === "az") {
        rows.sort((a, b) => a.headline.localeCompare(b.headline));
      } else {
        rows.sort((a, b) => a.section_order - b.section_order || (a.rank ?? 999) - (b.rank ?? 999));
      }
      return rows;
    }
    function groupBySection(rows) {
      const groups = [];
      const index = new Map();
      for (const row of rows) {
        if (!index.has(row.section_id)) {
          index.set(row.section_id, groups.length);
          groups.push({ id: row.section_id, title: row.section_title, rows: [] });
        }
        groups[index.get(row.section_id)].rows.push(row);
      }
      return groups;
    }
    function featuredCard(f) {
      const thumb = f.image ? `<img src="${encodeURI(f.image)}" loading="lazy" alt="${esc(f.headline)}">` : `<div class="placeholder"></div>`;
      const statusCls = f.status === "needs-review" ? "status-warn" : "status-good";
      const eyebrow = [f.badge, f.source_app, f.status].filter(Boolean)
        .map((bit, i) => `<span class="${i === 2 ? statusCls : ""}">${esc(bit)}</span>`).join("");
      const names = (f.names || []).map(n => `<span>${esc(n)}</span>`).join("");
      const files = (f.files || []).map(p => `<a href="${encodeURI(p)}" target="_blank">${esc(p.split("/").pop())}</a>`).join("");
      return `<article class="card">
        <div class="shot">${thumb}</div>
        <div class="copy">
          <div class="eyebrow">${eyebrow}</div>
          <h3 class="headline">${esc(f.headline)}</h3>
          ${f.summary ? `<p>${esc(f.summary)}</p>` : ""}
          ${f.takeaway ? `<div class="takeaway"><strong>Takeaway:</strong> ${esc(f.takeaway)}</div>` : ""}
          <div class="names">${names}</div>
          <details>
            <summary>Source: ${esc(f.entry_id)}</summary>
            <div class="files">${files}</div>
          </details>
        </div>
      </article>`;
    }
    function standardRow(f) {
      const cls = f.status === "needs-review" ? "warn" : "good";
      const label = f.status === "needs-review" ? "Review" : "OK";
      return `<div class="compact-row">
        <span class="mini-badge ${cls}">${label}</span>
        <span class="compact-headline">${esc(f.headline)}</span>
        <span class="compact-takeaway">${esc(f.takeaway)}</span>
      </div>`;
    }
    function render() {
      const rows = filtered();
      $("shown").textContent = rows.length;
      const groups = groupBySection(rows);
      if (!groups.length) {
        $("sections").innerHTML = `<div class="empty">No findings match these filters.</div>`;
        return;
      }
      $("sections").innerHTML = groups.map(group => {
        const featured = group.rows.filter(f => f.tier === "featured");
        const standard = group.rows.filter(f => f.tier !== "featured");
        const featuredHtml = featured.map(featuredCard).join("");
        const standardHtml = standard.length
          ? `<div class="compact-list">${standard.map(standardRow).join("")}</div>`
          : "";
        return `<div class="section-block">
          <div class="section-head"><h3>${esc(group.title)}</h3><span>${group.rows.length} finding(s) &middot; ${featured.length} featured</span></div>
          <div class="cards">${featuredHtml}</div>
          ${standardHtml}
        </div>`;
      }).join("");
    }
    init();
  </script>
</body>
</html>
"""


def render(data: dict, title: str) -> str:
    digest = data.get("digest") or {}
    rows = flatten_findings(data)
    stats = build_stats(rows, len(digest.get("sections") or []))
    shortlist = digest.get("shortlist") or []

    html = TEMPLATE
    html = html.replace("__PAGE_TITLE__", title)
    html = html.replace("__MAIN_TITLE__", title)
    html = html.replace("__FINDINGS__", safe_json(rows))
    html = html.replace("__STATS__", safe_json(stats))
    html = html.replace("__SHORTLIST__", safe_json(shortlist))
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
    rows = flatten_findings(data)
    print(f"Wrote {out_path} ({len(rows)} findings)")


if __name__ == "__main__":
    main()

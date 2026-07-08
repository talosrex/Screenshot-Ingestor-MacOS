#!/usr/bin/env python3
"""Render a screenshot-content-ingest JSON output as a scrollable, filterable HTML dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_entries(data: Any) -> list[dict]:
    if isinstance(data, dict) and "entries" in data:
        return data["entries"] or []
    if isinstance(data, list):
        return data
    raise ValueError("Input JSON must be an object with an 'entries' array or a bare array of entries.")


def entry_view(entry: dict) -> dict:
    source = entry.get("source") or {}
    content = entry.get("content") or {}
    consolidation = entry.get("consolidation") or {}
    organization = entry.get("organization") or {}
    quality = entry.get("quality") or {}
    integrity = quality.get("integrity") or {}

    capture = " ".join(x for x in [entry.get("date"), entry.get("time")] if x) or None
    files = consolidation.get("source_images") or []

    return {
        "id": entry.get("id") or "unknown",
        "title": entry.get("title") or "(untitled)",
        "capture": capture,
        "source_app": source.get("app") or "unknown",
        "source_site": source.get("site") or "",
        "source_handle": source.get("account_or_author") or "",
        "source_confidence": source.get("confidence") or "unknown",
        "summary": content.get("summary") or "",
        "visible_text": content.get("visible_text") or "",
        "image_context": content.get("image_context") or "",
        "inferred_context": content.get("inferred_context") or "",
        "content_type": content.get("content_type") or "unknown",
        "files": files,
        "file_count": len(files),
        "is_consolidated": bool(consolidation.get("is_consolidated")),
        "overlap_notes": consolidation.get("overlap_notes") or [],
        "topics": organization.get("topics") or [],
        "tags": organization.get("tags") or [],
        "vault_fit": organization.get("vault_fit") or "not_assessed",
        "category_rationale": organization.get("category_rationale") or "",
        "ocr_confidence": quality.get("ocr_confidence") or "unknown",
        "interpretation_confidence": quality.get("interpretation_confidence") or "unknown",
        "integrity_label": integrity.get("label") or "unknown",
        "integrity_score": integrity.get("llm_confidence_score"),
        "review_notes": quality.get("review_notes") or [],
        "unresolved": quality.get("unresolved_uncertainties") or [],
    }


def top_counts(views: list[dict], key) -> list[list]:
    counts: dict[str, int] = {}
    for v in views:
        value = key(v)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not item:
                continue
            counts[item] = counts.get(item, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)


def build_stats(views: list[dict]) -> dict:
    return {
        "entries": len(views),
        "screenshots": sum(v["file_count"] for v in views),
        "needsReview": sum(1 for v in views if v["integrity_label"] in ("low", "medium")),
        "merged": sum(1 for v in views if v["is_consolidated"]),
        "sources": top_counts(views, lambda v: v["source_app"]),
        "vaults": top_counts(views, lambda v: v["vault_fit"]),
        "integrity": top_counts(views, lambda v: v["integrity_label"]),
    }


def safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</script", "<\\/script")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__PAGE_TITLE__</title>
  <style>
    :root {
      --bg: #f5f6f8;
      --panel: #fff;
      --text: #181b1f;
      --muted: #66707d;
      --line: #d8dee6;
      --accent: #0b766e;
      --blue: #2459a7;
      --warn: #9b5b00;
      --bad: #9a2c2c;
      --shadow: 0 10px 24px rgba(17, 24, 39, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .layout {
      display: grid;
      grid-template-columns: 330px 1fr;
      min-height: 100vh;
    }
    aside {
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      padding: 18px;
      background: var(--panel);
      border-right: 1px solid var(--line);
    }
    main {
      padding: 22px;
      min-width: 0;
    }
    h1 { margin: 0 0 4px; font-size: 22px; }
    h2 {
      margin: 20px 0 10px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .muted { color: var(--muted); font-size: 12px; }
    .stats {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      margin: 16px 0;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }
    .stat strong { display: block; font-size: 24px; line-height: 1.1; }
    label {
      display: block;
      margin: 12px 0 5px;
      font-size: 12px;
      color: var(--muted);
      font-weight: 700;
    }
    input, select {
      width: 100%;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    input:focus, select:focus {
      outline: 0;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(11,118,110,.14);
    }
    .checks { display: grid; gap: 8px; margin-top: 10px; }
    .check { display: flex; gap: 8px; align-items: center; }
    .check input { width: 16px; height: 16px; accent-color: var(--accent); }
    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 16px;
    }
    .pills, .tags { display: flex; gap: 6px; flex-wrap: wrap; }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 23px;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .pill.good { color: var(--accent); border-color: rgba(11,118,110,.28); background: rgba(11,118,110,.08); }
    .pill.warn { color: var(--warn); border-color: rgba(155,91,0,.25); background: rgba(155,91,0,.08); }
    .pill.bad { color: var(--bad); border-color: rgba(154,44,44,.25); background: rgba(154,44,44,.08); }
    .bar-list { display: grid; gap: 8px; }
    .bar-row {
      display: grid;
      grid-template-columns: 1fr 42px;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      align-items: center;
    }
    .track { height: 8px; border-radius: 999px; background: #eef1f5; overflow: hidden; margin-top: 3px; }
    .fill { height: 100%; width: var(--w); background: var(--accent); }
    .entries { display: grid; gap: 14px; }
    .entry {
      display: grid;
      grid-template-columns: minmax(160px, 230px) minmax(0, 1fr);
      gap: 14px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .preview {
      width: 100%;
      max-height: 430px;
      object-fit: contain;
      object-position: top;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #eef1f5;
    }
    .entry-head {
      display: flex;
      gap: 12px;
      justify-content: space-between;
      align-items: flex-start;
    }
    h3 { margin: 0 0 4px; font-size: 18px; line-height: 1.25; }
    .id { color: var(--blue); font-weight: 800; }
    .gist { margin: 10px 0; color: #333941; }
    .meta {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px 14px;
      color: var(--muted);
      font-size: 12px;
      margin: 10px 0;
    }
    .meta span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
    details { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }
    summary { cursor: pointer; color: var(--blue); font-weight: 700; }
    pre {
      white-space: pre-wrap;
      max-height: 360px;
      overflow: auto;
      padding: 10px;
      border-radius: 8px;
      background: #f0f2f5;
      border: 1px solid var(--line);
      font-size: 12px;
    }
    .files { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .files a {
      color: var(--blue);
      text-decoration: none;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 3px 7px;
      font-size: 12px;
    }
    .empty {
      padding: 28px;
      text-align: center;
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--muted);
    }
    @media (max-width: 960px) {
      .layout { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      main { padding: 16px; }
      .entry { grid-template-columns: 110px minmax(0, 1fr); }
      .preview { max-height: 240px; }
    }
    @media (max-width: 640px) {
      .entry { grid-template-columns: 1fr; }
      .meta { grid-template-columns: 1fr; }
      .topbar { display: grid; }
    }
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <h1>__SIDEBAR_TITLE__</h1>
      <div class="muted">__SIDEBAR_SUBTITLE__</div>
      <div class="stats">
        <div class="stat"><strong id="total">0</strong><span>entries</span></div>
        <div class="stat"><strong id="shown">0</strong><span>shown</span></div>
        <div class="stat"><strong id="shots">0</strong><span>screenshots</span></div>
        <div class="stat"><strong id="needs">0</strong><span>need review</span></div>
      </div>
      <label for="search">Search</label>
      <input id="search" type="search" placeholder="title, text, source, vault, tag">
      <label for="confidence">Integrity</label>
      <select id="confidence"></select>
      <label for="vault">Vault / category</label>
      <select id="vault"></select>
      <label for="source">Source</label>
      <select id="source"></select>
      <label for="topic">Topic</label>
      <select id="topic"></select>
      <label for="sort">Sort</label>
      <select id="sort">
        <option value="review">Needs review first</option>
        <option value="new">Newest first</option>
        <option value="old">Oldest first</option>
        <option value="vault">Vault / source / date</option>
      </select>
      <div class="checks">
        <label class="check"><input id="mergedOnly" type="checkbox"> Consolidated sequences only</label>
        <label class="check"><input id="withNoteOnly" type="checkbox"> Has review notes</label>
      </div>
      <h2>Vaults / categories</h2>
      <div id="vaultBars" class="bar-list"></div>
      <h2>Sources</h2>
      <div id="sourceBars" class="bar-list"></div>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h1>__MAIN_TITLE__</h1>
          <div class="muted">__MAIN_SUBTITLE__</div>
        </div>
        <div class="pills">
          <span class="pill good">screenshot-content-ingest</span>
        </div>
      </div>
      <div id="entries" class="entries"></div>
    </main>
  </div>
  <script>
    const ENTRIES = __ENTRIES__;
    const STATS = __STATS__;
    const state = { search: "", confidence: "all", vault: "all", source: "all", topic: "all", sort: "review", mergedOnly: false, withNoteOnly: false };
    const $ = id => document.getElementById(id);
    const els = ["search","confidence","vault","source","topic","sort","mergedOnly","withNoteOnly"].reduce((a, id) => (a[id] = $(id), a), {});

    function esc(value) {
      return String(value ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
    }
    function dateLabel(value) {
      if (!value) return "unknown";
      const d = new Date(value);
      return Number.isNaN(d.getTime()) ? value : d.toLocaleString([], { year:"numeric", month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit" });
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
    function init() {
      options(els.confidence, [...new Set(ENTRIES.map(e => e.integrity_label))].sort(), "integrity levels");
      options(els.vault, [...new Set(ENTRIES.map(e => e.vault_fit))].sort(), "vaults");
      options(els.source, [...new Set(ENTRIES.map(e => e.source_app))].sort(), "sources");
      options(els.topic, [...new Set(ENTRIES.flatMap(e => e.topics))].sort(), "topics");
      $("total").textContent = STATS.entries;
      $("shots").textContent = STATS.screenshots;
      $("needs").textContent = STATS.needsReview;
      bars($("vaultBars"), STATS.vaults);
      bars($("sourceBars"), STATS.sources);
      Object.entries(els).forEach(([key, input]) => input.addEventListener("input", () => {
        state[key] = input.type === "checkbox" ? input.checked : input.value;
        render();
      }));
      render();
    }
    function hay(e) {
      return [e.id, e.title, e.summary, e.visible_text, e.source_app, e.source_handle, e.vault_fit, e.topics.join(" "), e.tags.join(" "), e.files.join(" "), (e.review_notes||[]).join(" ")].join(" ").toLowerCase();
    }
    function filtered() {
      const q = state.search.trim().toLowerCase();
      let rows = ENTRIES.filter(e =>
        (!q || hay(e).includes(q)) &&
        (state.confidence === "all" || e.integrity_label === state.confidence) &&
        (state.vault === "all" || e.vault_fit === state.vault) &&
        (state.source === "all" || e.source_app === state.source) &&
        (state.topic === "all" || e.topics.includes(state.topic)) &&
        (!state.mergedOnly || e.is_consolidated) &&
        (!state.withNoteOnly || (e.review_notes && e.review_notes.length) || (e.unresolved && e.unresolved.length))
      );
      rows.sort((a, b) => {
        const ac = a.capture || "";
        const bc = b.capture || "";
        if (state.sort === "new") return bc.localeCompare(ac);
        if (state.sort === "old") return ac.localeCompare(bc);
        if (state.sort === "vault") return (a.vault_fit + a.source_app + ac).localeCompare(b.vault_fit + b.source_app + bc);
        const rank = { low: 0, medium: 1, high: 2, unknown: 1 };
        const ar = rank[a.integrity_label] ?? 1;
        const br = rank[b.integrity_label] ?? 1;
        return ar - br || bc.localeCompare(ac);
      });
      return rows;
    }
    function confClass(label) {
      if (label === "high") return "good";
      if (label === "low") return "bad";
      return "warn";
    }
    function card(e) {
      const cls = confClass(e.integrity_label);
      const files = e.files.map(f => `<a href="${encodeURI(f)}" target="_blank">${esc(f)}</a>`).join("");
      const tags = e.tags.slice(0, 7).map(t => `<span class="pill">${esc(t)}</span>`).join("");
      const preview = e.files[0] ? `<img class="preview" src="${encodeURI(e.files[0])}" loading="lazy" alt="${esc(e.title)}">` : `<div class="preview"></div>`;
      const notes = [...(e.review_notes || []), ...(e.unresolved || [])].join(" · ");
      return `<article class="entry">
        <div>${preview}</div>
        <div>
          <div class="entry-head">
            <div>
              <h3>${esc(e.title)}</h3>
              <div class="muted"><span class="id">${esc(e.id)}</span> · ${dateLabel(e.capture)} · ${esc(e.source_app)}</div>
            </div>
            <div class="pills">
              <span class="pill ${cls}">${esc(e.integrity_label)}${e.integrity_score != null ? " " + e.integrity_score.toFixed(2) : ""}</span>
              ${e.is_consolidated ? `<span class="pill good">merged ${e.file_count}</span>` : ""}
            </div>
          </div>
          <p class="gist">${esc(e.summary || e.title)}</p>
          <div class="meta">
            <span title="${esc(e.vault_fit)}">Vault: ${esc(e.vault_fit)}</span>
            <span title="${esc(e.topics.join(", "))}">Topics: ${esc(e.topics.join(", "))}</span>
            <span>OCR: ${esc(e.ocr_confidence)}</span>
            <span title="${esc(notes)}">Review: ${esc(notes || "none")}</span>
          </div>
          <div class="tags">${tags}</div>
          <details>
            <summary>Show extracted text and files</summary>
            <div class="files">${files}</div>
            <pre>${esc(e.visible_text || "[No usable OCR text]")}</pre>
          </details>
        </div>
      </article>`;
    }
    function render() {
      const rows = filtered();
      $("shown").textContent = rows.length;
      $("entries").innerHTML = rows.length ? rows.map(card).join("") : `<div class="empty">No entries match these filters.</div>`;
    }
    init();
  </script>
</body>
</html>
"""


def render(data: Any, page_title: str) -> str:
    views = [entry_view(e) for e in load_entries(data)]
    stats = build_stats(views)
    html = TEMPLATE
    html = html.replace("__PAGE_TITLE__", page_title)
    html = html.replace("__SIDEBAR_TITLE__", "Screenshot Ingest")
    html = html.replace("__SIDEBAR_SUBTITLE__", "Extracted, reviewed, and categorized entries")
    html = html.replace("__MAIN_TITLE__", "Screenshot Review Dashboard")
    html = html.replace("__MAIN_SUBTITLE__", "Scrollable, filterable view of every consolidated entry.")
    html = html.replace("__ENTRIES__", safe_json(views))
    html = html.replace("__STATS__", safe_json(stats))
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", help="Path to screenshot-content-ingest.json (or a bare JSON array of entries)")
    parser.add_argument("-o", "--output", default="screenshot-content-ingest.html", help="Output HTML file path")
    parser.add_argument("--title", default="Screenshot Extraction", help="Browser tab title for the dashboard")
    args = parser.parse_args()

    data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    html = render(data, args.title)

    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    entry_count = len(load_entries(data))
    print(f"Wrote {out_path} ({entry_count} entries)")


if __name__ == "__main__":
    main()

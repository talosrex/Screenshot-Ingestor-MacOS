#!/usr/bin/env python3
"""Serve the screenshot-content-ingest dashboard with a persistent triage queue.

Reuses generate_dashboard.py's entry-shaping functions so this renders the
same fields, then serves them from a local HTTP server instead of a static
file. Unlike the static dashboard, this one can save a triage decision per
entry (Good / Needs OCR redo / Needs manual title / Wrong vault / Merge or
split) to a `<source>.review.json` sidecar, so a later pass can reprocess
only the flagged entries instead of the whole batch.

Usage:
    python3 scripts/dashboard.py screenshot-content-ingest.json
    python3 scripts/dashboard.py --port 8901 /path/to/output.json
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_dashboard import build_stats, entry_view, load_entries, safe_json  # noqa: E402

TRIAGE_STATUSES = ["good", "needs_ocr_redo", "needs_manual_title", "wrong_vault", "needs_merge_split"]
TRIAGE_LABELS = {
    "good": "Good",
    "needs_ocr_redo": "Needs OCR redo",
    "needs_manual_title": "Needs manual title",
    "wrong_vault": "Wrong vault",
    "needs_merge_split": "Merge or split",
}

STATE: dict[str, Any] = {}
LOCK = threading.Lock()


def review_path_for(source_json: Path) -> Path:
    return source_json.with_name(source_json.stem + ".review.json")


def load_reviews(review_file: Path) -> dict[str, Any]:
    if review_file.exists():
        try:
            data = json.loads(review_file.read_text(encoding="utf-8"))
            if isinstance(data.get("reviews"), dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"review_file_version": 1, "reviews": {}}


def save_reviews(review_file: Path, source_name: str, reviews: dict[str, Any]) -> None:
    payload = {
        "review_file_version": 1,
        "source_json": source_name,
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "reviews": reviews,
    }
    tmp_path = review_file.with_name(review_file.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, review_file)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Screenshot Triage Dashboard</title>
<style>
  :root {
    --bg: #f5f6f8; --panel: #fff; --text: #181b1f; --muted: #66707d;
    --line: #d8dee6; --accent: #0b766e; --blue: #2459a7; --warn: #9b5b00; --bad: #9a2c2c;
    --shadow: 0 10px 24px rgba(17, 24, 39, .08);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  .layout { display: grid; grid-template-columns: 300px 1fr; min-height: 100vh; }
  aside { position: sticky; top: 0; height: 100vh; overflow: auto; padding: 18px; background: var(--panel); border-right: 1px solid var(--line); }
  main { padding: 22px; min-width: 0; }
  h1 { margin: 0 0 4px; font-size: 20px; }
  .muted { color: var(--muted); font-size: 12px; }
  .stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 16px 0; }
  .stat { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fff; }
  .stat strong { display: block; font-size: 22px; line-height: 1.1; }
  label { display: block; margin: 12px 0 5px; font-size: 12px; color: var(--muted); font-weight: 700; }
  input, select { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--text); font: inherit; }
  .entries { display: grid; gap: 14px; }
  .entry { display: grid; grid-template-columns: minmax(200px, 320px) minmax(0, 1fr); gap: 14px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); box-shadow: var(--shadow); }
  .preview { width: 100%; max-height: 520px; object-fit: contain; object-position: top; border: 1px solid var(--line); border-radius: 6px; background: #eef1f5; cursor: zoom-in; }
  .entry-head { display: flex; gap: 12px; justify-content: space-between; align-items: flex-start; }
  h3 { margin: 0 0 4px; font-size: 17px; line-height: 1.25; }
  .id { color: var(--blue); font-weight: 800; }
  .gist { margin: 8px 0; color: #333941; }
  .pills, .tags { display: flex; gap: 6px; flex-wrap: wrap; }
  .pill { display: inline-flex; align-items: center; min-height: 22px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); background: #fff; color: var(--muted); font-size: 12px; white-space: nowrap; }
  .pill.good { color: var(--accent); border-color: rgba(11,118,110,.28); background: rgba(11,118,110,.08); }
  .pill.warn { color: var(--warn); border-color: rgba(155,91,0,.25); background: rgba(155,91,0,.08); }
  .pill.bad { color: var(--bad); border-color: rgba(154,44,44,.25); background: rgba(154,44,44,.08); }
  .meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 14px; color: var(--muted); font-size: 12px; margin: 8px 0; }
  details { margin-top: 8px; border-top: 1px solid var(--line); padding-top: 8px; }
  summary { cursor: pointer; color: var(--blue); font-weight: 700; }
  pre { white-space: pre-wrap; max-height: 300px; overflow: auto; padding: 10px; border-radius: 8px; background: #f0f2f5; border: 1px solid var(--line); font-size: 12px; }
  .triage { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line); }
  .triage-buttons { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
  .triage-buttons button { padding: 6px 10px; border-radius: 6px; border: 1px solid var(--line); background: #fff; font: inherit; font-size: 12px; cursor: pointer; }
  .triage-buttons button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
  .triage-note { width: 100%; padding: 7px 9px; border: 1px solid var(--line); border-radius: 6px; font: inherit; font-size: 12px; }
  .saved-flash { color: var(--accent); font-size: 12px; margin-left: 6px; opacity: 0; transition: opacity .2s; }
  .saved-flash.show { opacity: 1; }
  .empty { padding: 28px; text-align: center; border: 1px dashed var(--line); border-radius: 8px; background: #fff; color: var(--muted); }
  .lightbox { position: fixed; inset: 0; background: rgba(10,12,16,.85); display: none; align-items: center; justify-content: center; z-index: 10; padding: 24px; }
  .lightbox.show { display: flex; }
  .lightbox img { max-width: 100%; max-height: 100%; }
  @media (max-width: 960px) {
    .layout { grid-template-columns: 1fr; }
    aside { position: static; height: auto; }
    .entry { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
  <div class="layout">
    <aside>
      <h1>Triage Dashboard</h1>
      <div class="muted">Flag ambiguous entries for targeted reprocessing.</div>
      <div class="stats">
        <div class="stat"><strong id="total">0</strong><span>entries</span></div>
        <div class="stat"><strong id="shown">0</strong><span>shown</span></div>
        <div class="stat"><strong id="untriaged">0</strong><span>untriaged</span></div>
        <div class="stat"><strong id="needs">0</strong><span>need review</span></div>
      </div>
      <label for="search">Search</label>
      <input id="search" type="search" placeholder="title, text, source, vault, tag">
      <label for="confidence">Integrity</label>
      <select id="confidence"></select>
      <label for="triage">Triage status</label>
      <select id="triage"></select>
      <label for="sort">Sort</label>
      <select id="sort">
        <option value="review">Needs review first</option>
        <option value="untriaged">Untriaged first</option>
        <option value="new">Newest first</option>
        <option value="old">Oldest first</option>
      </select>
    </aside>
    <main>
      <div id="entries" class="entries"></div>
    </main>
  </div>
  <div class="lightbox" id="lightbox"><img id="lightboxImg" alt=""></div>
  <script>
    const $ = id => document.getElementById(id);
    const els = ["search","confidence","triage","sort"].reduce((a, id) => (a[id] = $(id), a), {});
    const state = { search: "", confidence: "all", triage: "all", sort: "review" };
    let ENTRIES = [];
    let STATS = {};
    let STATUSES = [];
    let LABELS = {};

    function esc(value) {
      return String(value ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
    }
    function dateLabel(value) {
      if (!value) return "unknown";
      const d = new Date(value);
      return Number.isNaN(d.getTime()) ? value : d.toLocaleString([], { year:"numeric", month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit" });
    }
    function imgSrc(path) { return "/image?path=" + encodeURIComponent(path); }
    function confClass(label) {
      if (label === "high") return "good";
      if (label === "low") return "bad";
      return "warn";
    }
    function options(el, values, label) {
      el.innerHTML = `<option value="all">All ${label}</option>` + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    }

    async function fetchEntries() {
      const res = await fetch("/api/entries");
      const data = await res.json();
      ENTRIES = data.entries; STATS = data.stats; STATUSES = data.statuses; LABELS = data.labels;
      init();
    }

    async function saveTriage(entryId, status, note) {
      const res = await fetch("/api/triage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entry_id: entryId, status, note }),
      });
      if (!res.ok) { alert("Failed to save triage status: " + (await res.text())); return; }
      const entry = ENTRIES.find(e => e.id === entryId);
      if (entry) { entry.triage_status = status; entry.triage_note = note; }
      render();
      const flash = document.getElementById("flash-" + entryId);
      if (flash) { flash.classList.add("show"); setTimeout(() => flash.classList.remove("show"), 1200); }
    }

    function init() {
      options(els.confidence, [...new Set(ENTRIES.map(e => e.integrity_label))].sort(), "integrity levels");
      els.triage.innerHTML = `<option value="all">All statuses</option><option value="untriaged">Untriaged</option>` +
        STATUSES.map(s => `<option value="${s}">${esc(LABELS[s])}</option>`).join("");
      $("total").textContent = STATS.entries;
      $("untriaged").textContent = ENTRIES.filter(e => !e.triage_status).length;
      $("needs").textContent = STATS.needsReview;
      Object.entries(els).forEach(([key, input]) => input.addEventListener("input", () => {
        state[key] = input.value;
        render();
      }));
      render();
    }

    function hay(e) {
      return [e.id, e.title, e.summary, e.visible_text, e.source_app, e.source_handle, e.vault_fit, e.topics.join(" "), e.tags.join(" ")].join(" ").toLowerCase();
    }
    function filtered() {
      const q = state.search.trim().toLowerCase();
      let rows = ENTRIES.filter(e =>
        (!q || hay(e).includes(q)) &&
        (state.confidence === "all" || e.integrity_label === state.confidence) &&
        (state.triage === "all" || (state.triage === "untriaged" ? !e.triage_status : e.triage_status === state.triage))
      );
      rows.sort((a, b) => {
        const ac = a.capture || "", bc = b.capture || "";
        if (state.sort === "new") return bc.localeCompare(ac);
        if (state.sort === "old") return ac.localeCompare(bc);
        if (state.sort === "untriaged") return (a.triage_status ? 1 : 0) - (b.triage_status ? 1 : 0) || bc.localeCompare(ac);
        const rank = { low: 0, medium: 1, high: 2, unknown: 1 };
        return (rank[a.integrity_label] ?? 1) - (rank[b.integrity_label] ?? 1) || bc.localeCompare(ac);
      });
      return rows;
    }

    function triageControls(e) {
      const buttons = STATUSES.map(s =>
        `<button data-entry="${esc(e.id)}" data-status="${s}" class="${e.triage_status === s ? "active" : ""}">${esc(LABELS[s])}</button>`
      ).join("");
      return `<div class="triage">
        <div class="triage-buttons">${buttons}<span class="saved-flash" id="flash-${esc(e.id)}">Saved</span></div>
        <input class="triage-note" data-note-for="${esc(e.id)}" type="text" placeholder="Note (optional)" value="${esc(e.triage_note || "")}">
      </div>`;
    }

    function card(e) {
      const cls = confClass(e.integrity_label);
      const tags = e.tags.slice(0, 7).map(t => `<span class="pill">${esc(t)}</span>`).join("");
      const preview = e.files[0] ? `<img class="preview" data-lightbox src="${imgSrc(e.files[0])}" loading="lazy" alt="${esc(e.title)}">` : `<div class="preview"></div>`;
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
              ${e.triage_status ? `<span class="pill good">${esc(LABELS[e.triage_status])}</span>` : `<span class="pill warn">untriaged</span>`}
            </div>
          </div>
          <p class="gist">${esc(e.summary || e.title)}</p>
          <div class="meta">
            <span title="${esc(e.vault_fit)}">Vault: ${esc(e.vault_fit)}</span>
            <span title="${esc(e.topics.join(", "))}">Topics: ${esc(e.topics.join(", "))}</span>
          </div>
          <div class="tags">${tags}</div>
          <details>
            <summary>Show extracted text</summary>
            <pre>${esc(e.visible_text || "[No usable OCR text]")}</pre>
          </details>
          ${triageControls(e)}
        </div>
      </article>`;
    }

    function render() {
      const rows = filtered();
      $("shown").textContent = rows.length;
      $("entries").innerHTML = rows.length ? rows.map(card).join("") : `<div class="empty">No entries match these filters.</div>`;
      document.querySelectorAll(".triage-buttons button").forEach(btn => {
        btn.addEventListener("click", () => {
          const entryId = btn.dataset.entry;
          const note = document.querySelector(`[data-note-for="${CSS.escape(entryId)}"]`).value;
          saveTriage(entryId, btn.dataset.status, note);
        });
      });
      document.querySelectorAll('[data-note-for]').forEach(input => {
        input.addEventListener("change", () => {
          const entryId = input.dataset.noteFor;
          const entry = ENTRIES.find(e => e.id === entryId);
          if (entry && entry.triage_status) saveTriage(entryId, entry.triage_status, input.value);
        });
      });
      document.querySelectorAll("[data-lightbox]").forEach(img => {
        img.addEventListener("click", () => {
          $("lightboxImg").src = img.src;
          $("lightbox").classList.add("show");
        });
      });
    }
    $("lightbox").addEventListener("click", () => $("lightbox").classList.remove("show"));
    fetchEntries();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        pass

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json", status)

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_bytes(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif parsed.path == "/api/entries":
            self._send_entries()
        elif parsed.path == "/image":
            self._send_image(parse_qs(parsed.query))
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib method name
        parsed = urlparse(self.path)
        if parsed.path == "/api/triage":
            self._handle_triage()
        else:
            self.send_error(404)

    def _send_entries(self) -> None:
        with LOCK:
            reviews = STATE["reviews"]["reviews"]
            entries = []
            for view in STATE["views"]:
                merged = dict(view)
                record = reviews.get(view["id"])
                merged["triage_status"] = record["status"] if record else None
                merged["triage_note"] = record.get("note") if record else None
                entries.append(merged)
        self._send_json(
            {
                "entries": entries,
                "stats": STATE["stats"],
                "statuses": TRIAGE_STATUSES,
                "labels": TRIAGE_LABELS,
            }
        )

    def _send_image(self, query: dict[str, list[str]]) -> None:
        values = query.get("path")
        if not values:
            self.send_error(400, "missing path")
            return
        requested = values[0]
        if requested not in STATE["allowed_images"]:
            self.send_error(403, "path not in loaded entries")
            return
        path = Path(requested)
        if not path.is_file():
            self.send_error(404, "image not found")
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._send_bytes(path.read_bytes(), content_type)

    def _handle_triage(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "invalid JSON body")
            return
        entry_id = payload.get("entry_id")
        status = payload.get("status")
        note = payload.get("note")
        if entry_id not in STATE["entry_ids"]:
            self.send_error(404, "unknown entry_id")
            return
        if status not in TRIAGE_STATUSES:
            self.send_error(400, f"status must be one of {TRIAGE_STATUSES}")
            return
        with LOCK:
            STATE["reviews"]["reviews"][entry_id] = {
                "status": status,
                "note": note,
                "reviewed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            }
            save_reviews(STATE["review_file"], STATE["source_name"], STATE["reviews"]["reviews"])
        self._send_json({"ok": True})


def main() -> int:
    parser = argparse.ArgumentParser(description="Local triage dashboard for screenshot-content-ingest output.")
    parser.add_argument("input_json", help="Path to screenshot-content-ingest.json")
    parser.add_argument("--port", type=int, default=8765, help="Port to serve on (default 8765).")
    parser.add_argument("--review-file", help="Override the sidecar review file path.")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser.")
    args = parser.parse_args()

    source_json = Path(args.input_json).expanduser().resolve()
    data = json.loads(source_json.read_text(encoding="utf-8"))
    views = [entry_view(entry) for entry in load_entries(data)]
    stats = build_stats(views)

    review_file = Path(args.review_file).expanduser().resolve() if args.review_file else review_path_for(source_json)
    reviews = load_reviews(review_file)

    STATE["views"] = views
    STATE["stats"] = stats
    STATE["entry_ids"] = {view["id"] for view in views}
    STATE["allowed_images"] = {path for view in views for path in view["files"]}
    STATE["review_file"] = review_file
    STATE["source_name"] = source_json.name
    STATE["reviews"] = reviews

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Serving triage dashboard for {source_json} at {url}")
    print(f"Triage decisions save to {review_file}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

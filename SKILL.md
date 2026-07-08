---
name: screenshot-content-ingest
description: Extract, reconcile, consolidate, review, integrity-score, and categorize information from screenshot collections. Use when Codex needs to analyze screenshots for visible text, image context, metadata, capture timing, source app/site, overlapping sequential captures, topics, tags, LLM confidence scores for extracted content integrity, and optional fit against a user-provided vault or sorting taxonomy.
---

# Screenshot Content Ingest

## Overview

Use this skill to turn a folder or list of screenshots into consolidated content records with provenance, timestamps, source/app guesses, topic labels, tags, review notes, and LLM confidence scores for extracted content integrity.

Do not assume a default screenshot folder. If the user does not provide screenshot paths, ask for the folder or files to analyze before doing any extraction. Do not hardcode a vault path; if the user wants category matching against a vault or taxonomy and has not provided its location, ask for that location separately.

## Workflow

1. Confirm inputs.
   - Required: screenshot folder or screenshot file paths.
   - Optional: output folder, vault/taxonomy path for category matching, date range, recursion preference.
   - If the screenshot location is missing, ask only for that first.
2. Inventory the screenshots.
   - Run `python3 scripts/inventory_screenshots.py <screenshot-path> --recursive --output <output-json>` when local filesystem access is available.
   - Use the JSON inventory for file metadata, dimensions, exact-duplicate hashes, perceptual hashes (when Pillow is installed), inferred capture times, and candidate groups: timestamp-based groups within the window, plus `phash_only` groups for visually similar captures that fell outside the timestamp window (e.g. a slow multi-slide scroll).
   - If script execution is unavailable, manually list files and preserve path, filename, modified time, creation time if available, dimensions, and format.
3. Extract content from each screenshot.
   - Read metadata first: filename timestamps, filesystem times, EXIF/PNG text when present, dimensions, file size, and origin hints. Screenshot EXIF/XMP metadata does not carry recognized text (iOS Live Text indexing lives in the Photos library database, not in the exported file), so do not expect OCR text to already be present in file metadata.
   - Run on-device OCR before reading images: `python3 scripts/run_vision_ocr.py <screenshot-path> --recursive -o <ocr-output-json>` when local filesystem access is available on macOS. It batches Apple's Vision framework (`VNRecognizeTextRequest`, accurate mode with language correction) over the screenshots and writes per-image recognized text, per-line confidence, and bounding boxes. It compiles a small helper binary on first run (needs Xcode Command Line Tools) and reuses it after that.
   - Treat the Vision OCR output as raw evidence, not the final `visible_text`: it includes UI chrome (status bar clock/battery, like/reply counts, icons) that must be filtered out during extraction, and reading order is only an approximation from bounding-box position — verify against the actual screenshot for multi-column or overlapping layouts.
   - If `run_vision_ocr.py` is unavailable (non-macOS, no Command Line Tools, no filesystem access), fall back to reading visible image content directly and running OCR through whatever vision capability is available.
   - For a specific screenshot where Vision OCR and your own reading still disagree, are low-confidence, or look garbled, run `python3 scripts/ocr_fallback.py <path> --screenshot-type <hint> --crop-heuristic trim-top-bottom` as a second cross-check. It sweeps Tesseract preprocessing variants and PSM modes and returns a best guess plus every variant tried; treat it as supporting evidence, not a replacement for Vision OCR or your own reading. It requires `tesseract`, `pytesseract`, and `pillow` — if any are missing it reports `ocr_available: false` rather than failing, so note that once in `run.notes` and continue without it.
   - Record visible text separately from inferred context.
   - Capture source/app/site from browser chrome, app UI, status bars, watermarks, URLs, usernames, handles, post controls, or filename/source metadata.
4. Consolidate near-duplicate or sequential captures.
   - Compare screenshots captured within 20 seconds of each other.
   - Merge into one entry only when they appear to be the same content surface or a continuous sequence, such as overlapping scroll captures, adjacent post/thread captures, article sections, or repeated captures of one app view.
   - Keep them separate when app/source, topic, account, visible content, or context changes.
   - When merging, deduplicate overlapping text, preserve unique text in reading order, and keep all source screenshot paths in `source_images`.
5. Review for accuracy and extraction integrity.
   - Spawn a subagent when available with the draft extraction and raw screenshot paths. Ask it to find OCR errors, false merges, missed overlaps, unsupported interpretations, wrong source guesses, and context mismatches.
   - If subagents are unavailable, perform a separate review pass yourself before finalizing.
   - Assign or revise content integrity confidence scores after the review pass.
6. Organize and categorize.
   - Spawn a second subagent when available with the reviewed extraction and optional vault/taxonomy path. Ask it to label, sort, and tag entries by date, time, source/app/site, topic, content type, and vault/category fit.
   - If no vault/taxonomy path is supplied, categorize using the extracted topics only and mark `vault_fit` as `not_assessed`.
7. Produce outputs.
   - Write a machine-readable JSON file and a readable Markdown summary unless the user requests a different format.
   - Include unresolved uncertainties, low-confidence fields, and per-entry content integrity scores rather than forcing guesses.
   - Also render a scrollable HTML dashboard from the JSON: run `python3 scripts/generate_dashboard.py <output-json> -o <output-html>`. This produces a single self-contained file with a filter/search sidebar (integrity, vault/category, source, topic, sort, consolidated-only, has-review-notes) and a scrollable list of entry cards (image preview, title, summary, metadata, tags, and collapsible full extracted text). Skip this step only if the user explicitly says they don't want an HTML view.
   - The dashboard reads `source_images` paths directly as image `src` values, so keep the HTML output alongside the original screenshots (or use paths relative to where the HTML will be opened) so previews resolve.
8. Triage ambiguous entries (optional).
   - When entries are flagged `needs_visual_review` or otherwise look uncertain, run `python3 scripts/dashboard.py <output-json>` to open a local, interactive triage dashboard (same entry cards as the static HTML, served live at `http://127.0.0.1:8765`).
   - Use it to mark each entry Good / Needs OCR redo / Needs manual title / Wrong vault / Merge or split, with an optional note. Decisions save immediately to `<output-json base name>.review.json`.
   - Reprocess only entries whose sidecar status is not `good` (using their `consolidation.source_images`) instead of rerunning the full batch.
9. Generate a digest (optional).
   - This is a synthesis pass over the finished, reviewed entries, not a re-extraction: it reads `entries[]` text (titles, summaries, tags, confidence) and does not need to view the screenshots again, so it does not require a vision-capable model.
   - For roughly 40 entries or fewer, spawn one subagent with the full reviewed JSON and the "Digest pass — draft" prompt below. It drafts one finding per entry, proposes thematic sections, and marks featured/standard tiers directly.
   - For larger batches (this workflow is commonly run at ~500 entries at a time), do this automatically in two passes so no single call has to hold hundreds of entries, lose consistency across them, or regenerate hundreds of findings' worth of text in one output — split the work yourself, do not ask the user to pre-batch the input:
     1. **Map.** Split `entries[]` into batches of roughly 40-50 (grouped by shared topic/tags when that grouping is already coherent, otherwise sequential) — a 500-entry run is about 10-13 batches. Spawn one subagent per batch **in parallel** with the "Digest pass — draft" prompt. Each batch drafts a finding per entry, proposes a section name, and notes each finding's relative strength, but does not assign a final featured/standard tier — that call can't see the whole set.
     2. **Reduce.** Spawn one subagent with a *compact* summary of every draft finding (entry_id, proposed section, headline, takeaway, strength note — not the full entries again) and the "Digest pass — reconcile" prompt. It only returns routing decisions (final section, tier, rank) per entry_id, never rewriting the finding text itself, so its own output stays small however many entries there are. Merge those routing decisions back onto the full finding records from the map step yourself to assemble the final `digest` block — the reconcile subagent's job is to organize, not to re-author.
   - Either way, coverage is complete: every entry gets exactly one finding, none are dropped.
   - Add the resulting `digest` block to the same output JSON (see `references/output-schema.md`) — do not create a second JSON file or edit `entries[]`.
   - Render it: run `python3 scripts/generate_digest.py <output-json> -o <digest-html>`. This produces a newsletter-style page with a hero header, an editor's shortlist, per-section navigation, and a takeaway box on each featured finding.
   - Skip this step unless the user asks for a digest; it adds an editorial layer on top of the neutral extraction record and is meant to be regenerated freely (e.g. after triage corrections) without re-running extraction.

## Extraction Rules

- Treat screenshot text as evidence and inferences as hypotheses.
- Prefer exact visible text over paraphrase for short UI labels, names, titles, dates, and handles.
- Do not invent missing author names, apps, URLs, timestamps, or topics.
- Normalize capture dates to ISO 8601 when possible and keep the original timestamp evidence.
- Record confidence for source, date/time, OCR, topic, category decisions, and overall extracted content integrity.
- Keep provenance: every consolidated entry must list the source screenshot paths that contributed to it.
- Do not delete or move source screenshots unless the user explicitly asks.

## Content Integrity Confidence

Assign a per-entry LLM integrity confidence score for how likely the final extracted record preserves the screenshot content without material OCR, merge, ordering, attribution, timestamp, summary, or inference errors. This is confidence in the extraction result, not confidence that the source content itself is true.

Use a 0.00-1.00 score:
- `high`: 0.85-1.00
- `medium`: 0.60-0.84
- `low`: 0.00-0.59

Score field-level integrity for visible text, source attribution, timestamp, consolidation, and summary when applicable. Use `null` for fields that do not apply. Keep scores conservative and explain the basis and risk factors.

Lower integrity scores for blurred or cropped screenshots, low resolution, partial text, ambiguous source/app/site, conflicting timestamp evidence, OCR uncertainty, inferred missing context, uncertain merge or deduplication decisions, or entries that did not receive a separate review pass.

Raise integrity scores only when the visible content is legible, the source and timestamp evidence are clear, all source images support the same record, deduplication preserves reading order, and review found no material issues.

## Confidence-Gated Summaries

Do not fabricate `content.summary` when confidence is low. If `ocr_confidence` or `interpretation_confidence` is `low`, or the text is too garbled or partial to summarize faithfully, set `content.summary` to `null` and `quality.needs_visual_review` to `true`. Prioritize showing `content.visible_text` (raw or partial transcription) over an invented gist, and record why in `review_notes`. `needs_visual_review` is set by this pipeline only; separate human triage decisions belong in the dashboard's review sidecar (see step 8).

## 20-Second Grouping

Use the inventory script's `candidate_groups` only as candidates. The final merge decision must consider visual and textual continuity.

Merge when:
- capture times are within 20 seconds,
- screenshots share the same apparent source/app/site or content surface,
- visible text or layout overlaps, or the sequence is clearly adjacent content from one post/thread/article/page.

Do not merge when:
- the screenshots are from different apps, sites, accounts, chats, documents, or browser tabs,
- the repeated time window is only due to a burst of unrelated captures,
- one screenshot is metadata/navigation while another is unrelated content,
- the interpretation would erase materially different context.

When perceptual hash data is present, use a group's `phash_similarity` to add confidence to a timestamp-based candidate, or treat a `phash_only` group as a weaker-evidence candidate needing extra scrutiny — visually similar but unrelated screens (e.g. two separate visits to the same settings screen) can produce a low Hamming distance without being a real sequence.

## Subagent Prompts

Use these as task prompts when multi-agent tools are available.

Quality review:

```text
Review this screenshot extraction draft against the raw screenshot paths. Identify OCR mistakes, false merges, missed overlaps, weak or unsupported interpretations, wrong source/app guesses, date/time issues, and anything that does not fit the visible context. Return only actionable corrections and confidence notes.
For each entry, flag anything that should lower the content integrity confidence score.
```

Organization pass:

```text
Organize this reviewed screenshot extraction into labeled records. Sort and tag each entry by date, time, source/app/site, topic, content type, and category fit. If a vault or taxonomy path is provided, inspect its structure and map entries to likely categories; otherwise mark vault_fit as not_assessed. Return concise labels, tags, and category rationale.
```

Digest pass — draft (optional, see step 9; used directly for small batches, or as the map step for large ones):

```text
Draft digest findings for these reviewed screenshot entries — they may be the full run or one batch of a larger one. Work from the JSON text only — you do not need to view the screenshots. Give every entry exactly one finding (entry_id); do not drop any and do not combine multiple entries into one finding. Propose a thematic section title for each finding based on its topic/tags; use clear, general section names, since batches from the same run may later be merged if they cover the same theme. Write a headline, a one-sentence takeaway (a judgment or recommended action, not a restatement of the summary), and a short badge. Note each finding's relative strength in one short phrase so a later pass (or your own judgment, if this is the only batch) can decide which findings deserve featured treatment. If an entry's integrity is low or its triage status (from the review sidecar, when available) is not "good", set status to "needs-review" and keep the takeaway conservative rather than confidently asserting a judgment on unreliable data. If this is the only batch for the run, also mark only the handful of strongest findings per section as tier "featured" (the rest "standard") and write a short top-of-page shortlist of 3-6 suggested next actions.
```

Digest pass — reconcile (large batches only, after all drafts are done):

```text
You have compact summaries (entry_id, proposed section, headline, takeaway, strength note) of draft digest findings from multiple batches covering every entry in this run — not the full finding text and not the raw entries. Do not rewrite the headline, takeaway, or badge; your job is to organize, not re-author. Merge sections that cover the same theme under one canonical title and order sections sensibly. Using each finding's strength note, decide across the entire set which findings deserve tier "featured" (only a handful per section) and mark the rest "standard" — compare strength across all batches, not just within one. Assign a final rank within each section. Write a top-of-page shortlist of 3-6 suggested next actions drawing from across all sections. Return, for every entry_id (each must appear exactly once): final section id/title, tier, and rank only — the caller will merge this back onto the original drafted findings.
```

## Output Schema

Follow `references/output-schema.md` for the final JSON and Markdown structure.

Recommended filenames:
- `screenshot-content-ingest.json`
- `screenshot-content-ingest.md`
- `screenshot-content-ingest.html`
- `screenshot-content-ingest.review.json` (written by the triage dashboard, not by this workflow directly)
- `screenshot-content-ingest-digest.html` (written by the digest renderer, see step 9)

## Resources

- `scripts/inventory_screenshots.py`: build a screenshot metadata inventory, exact/perceptual-hash data, and candidate groups within a configurable time window.
- `scripts/run_vision_ocr.py` / `scripts/vision_ocr.swift`: batch on-device OCR via Apple's Vision framework (see step 3). macOS only; auto-compiles `scripts/bin/vision_ocr` on first use.
- `scripts/ocr_fallback.py`: optional Tesseract-based OCR cross-check with preprocessing variants and PSM sweeps (see step 3). Requires `tesseract`, `pytesseract`, and `pillow`; feature-detects and reports unavailability rather than failing.
- `scripts/generate_dashboard.py`: render the final JSON output as a scrollable, filterable, static HTML dashboard (see step 7).
- `scripts/dashboard.py`: serve the same entries from a local triage dashboard with a persistent Good/Needs OCR redo/Needs manual title/Wrong vault/Merge or split queue (see step 8).
- `scripts/generate_digest.py`: render a JSON output's `digest` block as a newsletter-style HTML page with featured/standard tiered findings (see step 9).
- `references/output-schema.md`: field definitions for extracted, consolidated, reviewed, and categorized records.

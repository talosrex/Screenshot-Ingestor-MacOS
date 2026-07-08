# Output Schema

Use this schema for final screenshot extraction outputs. Include fields as `null`, empty arrays, or `unknown` when evidence is unavailable.

The JSON below is also the direct input to `scripts/generate_dashboard.py`, which renders it as a scrollable HTML dashboard (`screenshot-content-ingest.html`). The generator reads `entries[].consolidation.source_images` as image paths, `entries[].organization.*` for filtering, and `entries[].quality.integrity.label` for the confidence pill, so keep those fields populated even when other fields are `null`/`unknown`.

## JSON

```json
{
  "run": {
    "screenshot_inputs": [],
    "output_created_at": "ISO-8601 timestamp",
    "window_seconds": 20,
    "vault_or_taxonomy_path": null,
    "notes": []
  },
  "entries": [
    {
      "id": "entry-001",
      "title": "short descriptive title",
      "date": "YYYY-MM-DD or null",
      "time": "HH:MM:SS or null",
      "timezone": "IANA timezone or null",
      "timestamp_evidence": ["filename", "filesystem_mtime", "visible_text"],
      "source": {
        "app": "app name or unknown",
        "site": "site/domain or unknown",
        "url": "visible URL or null",
        "account_or_author": "visible account/person or null",
        "confidence": "high|medium|low"
      },
      "content": {
        "visible_text": "deduplicated OCR/manual transcription, may be partial or garbled",
        "summary": "brief factual summary, or null when quality.needs_visual_review is true",
        "image_context": "non-text visual context",
        "inferred_context": "explicitly marked interpretation",
        "content_type": "post|article|chat|email|note|image|receipt|settings|other|unknown"
      },
      "consolidation": {
        "is_consolidated": false,
        "reason": "why files were merged or kept separate",
        "source_images": [],
        "overlap_notes": []
      },
      "organization": {
        "topics": [],
        "tags": [],
        "vault_fit": "not_assessed|none|category/path",
        "category_rationale": "short rationale or null"
      },
      "quality": {
        "ocr_confidence": "high|medium|low",
        "interpretation_confidence": "high|medium|low",
        "needs_visual_review": false,
        "integrity": {
          "llm_confidence_score": 0.0,
          "label": "high|medium|low",
          "field_scores": {
            "visible_text": 0.0,
            "source_attribution": 0.0,
            "timestamp": 0.0,
            "consolidation": 0.0,
            "summary": 0.0
          },
          "basis": [],
          "risk_factors": []
        },
        "review_notes": [],
        "unresolved_uncertainties": []
      }
    }
  ]
}
```

## Markdown

Use this structure for the readable summary:

```markdown
# Screenshot Content Ingest

Generated: YYYY-MM-DD HH:MM
Inputs: path(s)

## Entry 001: Title

- Date/time: value or unknown
- Source: app/site/account with confidence
- Topic: concise topic
- Tags: tag list
- Vault/category fit: value or not_assessed
- Source images: path list
- Confidence: OCR / interpretation / integrity score and label
- Integrity field scores: visible text, source attribution, timestamp, consolidation, summary

### Extracted Text

Visible text, deduplicated and ordered.

### Context

Factual visual context and clearly marked inferences.

### Review Notes

Corrections, uncertainties, and caveats.
```

## Integrity Scoring

Use `quality.integrity.llm_confidence_score` for the LLM's confidence that the extracted record faithfully preserves the visible screenshot content. It does not judge whether the screenshot's underlying claims are true.

Score from 0.00 to 1.00 and derive `label` from the same value:
- `high`: 0.85-1.00
- `medium`: 0.60-0.84
- `low`: 0.00-0.59

Use the same 0.00-1.00 scale for `field_scores`. Set a field score to `null` when that field is not applicable, such as consolidation for a single source image. Put evidence supporting the score in `basis` and known weaknesses in `risk_factors`.

## Confidence-Gated Summaries

Set `quality.needs_visual_review` to `true` whenever `ocr_confidence` is `low`, `interpretation_confidence` is `low`, or the visible text is too garbled or partial to summarize faithfully. When set, do not fabricate `content.summary` from noisy text — set it to `null` and let `content.visible_text` plus `review_notes` carry the record. This field is pipeline-set only; human triage decisions (Good / Needs OCR redo / Needs manual title / Wrong vault / Merge or split) are recorded separately by `scripts/dashboard.py` in a `.review.json` sidecar next to the output JSON, not in this schema.

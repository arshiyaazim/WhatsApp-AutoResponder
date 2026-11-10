from __future__ import annotations

import json
import re
from typing import Any


STATUSES = {"complete", "partial", "unclear"}


def normalize_ocr_result(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {
            "extracted_text": raw[:100_000],
            "language": "unknown",
            "extraction_status": "partial" if raw.strip() else "unclear",
            "confidence_or_uncertainty": {"confidence": None, "uncertainty": "Provider did not return structured OCR data; no calibrated confidence is available."},
            "warnings": ["Provider response was not valid OCR JSON; raw extracted text is shown."],
        }
    if not isinstance(data, dict):
        data = {}
    extracted = data.get("extracted_text", "")
    if not isinstance(extracted, str):
        extracted = ""
    language = data.get("language", "unknown")
    if not isinstance(language, str) or len(language) > 100:
        language = "unknown"
    status = data.get("extraction_status", "partial")
    if not isinstance(status, str) or status not in STATUSES:
        status = "partial"
    raw_warnings = data.get("warnings", [])
    if isinstance(raw_warnings, str):
        raw_warnings = [raw_warnings]
    if not isinstance(raw_warnings, list):
        raw_warnings = ["Provider returned invalid warning metadata."]
    warnings = [str(item)[:500] for item in raw_warnings[:20]]
    uncertainty = "No calibrated confidence score was supplied by the provider."
    if status != "complete" or "[unclear]" in extracted.lower():
        uncertainty = "Some text may be unclear; review the marked spans and warnings."
    return {
        "extracted_text": extracted[:100_000],
        "language": language,
        "extraction_status": status,
        "confidence_or_uncertainty": {"confidence": None, "uncertainty": uncertainty},
        "warnings": warnings,
    }

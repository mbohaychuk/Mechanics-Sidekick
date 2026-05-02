"""Engine-variant + table-type classifier for chunk metadata.

Engine variant is determined per-document (cached) via a two-pass strategy:
filename regex first, LLM fallback when the filename is ambiguous. Table type
is determined per-table from section heading + column header keywords — no
LLM call needed.
"""
import json
import re

from app.services.ollama_service import OllamaService


_VARIANT_REGEX = re.compile(r"\b(4\.2L|6\.0L|5\.2L|W12)\b", re.IGNORECASE)
_VARIANT_NORMALIZE = {"w12": "W12", "4.2l": "4.2L", "6.0l": "6.0L", "5.2l": "5.2L"}

_TABLE_TYPE_KEYWORDS = {
    "torque": ("torque", "tightening", " nm", "n·m", "ft-lb"),
    "fluid": ("fluid", "capacity", "oil", "coolant", "lubricant"),
    "electrical": ("fuse", "amp", "ampere", "voltage", "wiring", "relay"),
    "fitment": ("fitment", "track width", "wheelbase", "diameter", "wear limit"),
    "dtc": ("dtc", "diagnostic trouble", "fault code", "p0", "p1"),
}


class MetadataExtractor:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def extract_engine_variant(self, filename: str, sample_text: str) -> str | None:
        """Return canonical engine variant tag or None if unknown.

        Filename regex first; LLM fallback if no match. The LLM returns JSON
        `{engine_variant: "4.2L" | "6.0L" | "5.2L" | "W12" | "both" | "unknown"}`.
        Permissively scans free-form output for the same tokens on parse failure.
        """
        match = _VARIANT_REGEX.search(filename)
        if match:
            return _VARIANT_NORMALIZE[match.group(1).lower()]

        # Filename ambiguous → ask the small model.
        prompt = (
            "You classify automotive service-manual content by engine variant.\n\n"
            f"Filename: {filename}\n\n"
            "Content sample:\n"
            f"{sample_text[:1500]}\n\n"
            "Reply with a single JSON object:\n"
            '{"engine_variant": "4.2L" | "6.0L" | "5.2L" | "W12" | "both" | "unknown"}\n'
            "Use 'both' only if the content explicitly applies to multiple engines. "
            "Use 'unknown' if the content does not specify."
        )
        response = self._ollama.chat([{"role": "user", "content": prompt}], self._model)

        # Strict JSON parse.
        try:
            parsed = json.loads(response)
            value = parsed.get("engine_variant", "").lower()
            if value in _VARIANT_NORMALIZE:
                return _VARIANT_NORMALIZE[value]
            if value == "both":
                return "both"
            if value == "unknown":
                return None
        except (json.JSONDecodeError, AttributeError):
            pass

        # Permissive fallback: scan free-form text for a variant token.
        match = _VARIANT_REGEX.search(response)
        if match:
            return _VARIANT_NORMALIZE[match.group(1).lower()]
        return None

    def classify_table_type(self, section_title: str | None, header: list[str]) -> str | None:
        """Return one of `torque | fluid | electrical | fitment | dtc | None`."""
        haystack = " ".join([section_title or "", *header]).lower()
        for table_type, keywords in _TABLE_TYPE_KEYWORDS.items():
            if any(kw in haystack for kw in keywords):
                return table_type
        return None

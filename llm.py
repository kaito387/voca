from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompt.md"
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEFAULT_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


@dataclass(slots=True)
class GeneratedCard:
    sentence_cloze: str
    hint: str
    meaning: str
    structure: str
    usage: str
    extra: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "sentence_cloze": self.sentence_cloze,
            "hint": self.hint,
            "meaning": self.meaning,
            "structure": self.structure,
            "usage": self.usage,
            "extra": self.extra,
            "source": self.source,
        }


def load_prompt_template() -> str:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template not found: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def _build_user_payload(sentence: str, target: str, note: str | None = None) -> str:
    payload: dict[str, Any] = {"sentence": sentence, "target": target}
    if note:
        payload["note"] = note
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_json_text(raw_content: str) -> str:
    stripped = raw_content.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def _normalize_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if value is None:
        normalized = ""
    elif isinstance(value, str):
        normalized = value.strip()
    else:
        normalized = str(value).strip()

    if not allow_empty and not normalized:
        raise ValueError(f'DeepSeek response is missing a valid "{field_name}" field.')
    return normalized


def _parse_card_response(raw_content: str) -> GeneratedCard:
    json_text = _extract_json_text(raw_content)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"DeepSeek returned invalid JSON: {raw_content}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek response must be a JSON object.")

    sentence_cloze = _normalize_text(parsed.get("sentence_cloze"), "sentence_cloze")
    hint = _normalize_text(parsed.get("hint"), "hint")
    meaning = _normalize_text(parsed.get("meaning"), "meaning")
    structure = _normalize_text(parsed.get("structure", ""), "structure", allow_empty=True)
    usage = _normalize_text(parsed.get("usage"), "usage")
    extra = _normalize_text(parsed.get("extra"), "extra")
    source = _normalize_text(parsed.get("source", ""), "source", allow_empty=True)

    if "{{c1::" not in sentence_cloze:
        raise ValueError(
            f'Generated sentence must contain cloze deletion format {{{{c1::...}}}}. Got: {sentence_cloze}'
        )

    return GeneratedCard(
        sentence_cloze=sentence_cloze,
        hint=hint,
        meaning=meaning,
        structure=structure,
        usage=usage,
        extra=extra,
        source=source,
    )


def generate_anki_card(sentence: str, target: str, note: str | None = None) -> GeneratedCard:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    system_prompt = load_prompt_template()
    user_payload = _build_user_payload(sentence=sentence, target=target, note=note)
    client = OpenAI(api_key=api_key, base_url=DEFAULT_BASE_URL)

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                stream=False,
                temperature=0.2,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("DeepSeek returned an empty response.")
            return _parse_card_response(content)
        except Exception as exc:  # pragma: no cover - network and provider errors vary.
            last_error = exc
            if attempt < 2:
                continue

    assert last_error is not None
    raise RuntimeError(f"Failed to generate Anki card: {last_error}") from last_error
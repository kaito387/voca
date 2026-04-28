from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompt.md"
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEFAULT_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


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


def _parse_card_response(raw_content: str) -> dict[str, str]:
    json_text = _extract_json_text(raw_content)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"DeepSeek returned invalid JSON: {raw_content}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek response must be a JSON object.")

    front = parsed.get("front")
    back = parsed.get("back")
    extra = parsed.get("extra", "")

    if not isinstance(front, str) or not front.strip():
        raise ValueError('DeepSeek response is missing a valid "front" field.')
    if not isinstance(back, str) or not back.strip():
        raise ValueError('DeepSeek response is missing a valid "back" field.')
    if not isinstance(extra, str):
        extra = str(extra)

    return {"front": front.strip(), "back": back.strip(), "extra": extra.strip()}


def generate_anki_card(sentence: str, target: str) -> dict[str, str]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    system_prompt = load_prompt_template()
    user_payload = _build_user_payload(sentence=sentence, target=target)
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
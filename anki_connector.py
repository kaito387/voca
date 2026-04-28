from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from llm import GeneratedCard


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / ".ankiconnect_config"
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"
DEFAULT_DECK_NAME = "Default"
DEFAULT_MODEL_NAME = "Basic"
PROXIES = {
    "http://": "socks5://127.0.0.1:7890",
    "https://": "socks5://127.0.0.1:7890",
}

CARD_FIELDS = (
    "sentence_cloze",
    "hint",
    "meaning",
    "structure",
    "usage",
    "extra",
    "source",
)


@dataclass(slots=True)
class AnkiConnectConfig:
    deck_name: str = DEFAULT_DECK_NAME
    model_name: str = DEFAULT_MODEL_NAME
    server_url: str = DEFAULT_SERVER_URL
    field_map: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnkiConnectConfig":
        raw_field_map = data.get("field_map")
        field_map: dict[str, str] | None = None
        if isinstance(raw_field_map, dict):
            normalized_field_map = {
                str(source).strip(): str(target).strip()
                for source, target in raw_field_map.items()
                if str(source).strip() and str(target).strip()
            }
            field_map = normalized_field_map or None

        return cls(
            deck_name=str(data.get("deck_name", DEFAULT_DECK_NAME)).strip() or DEFAULT_DECK_NAME,
            model_name=str(data.get("model_name", DEFAULT_MODEL_NAME)).strip() or DEFAULT_MODEL_NAME,
            server_url=str(data.get("server_url", DEFAULT_SERVER_URL)).strip() or DEFAULT_SERVER_URL,
            field_map=field_map,
        )

    def to_dict(self) -> dict[str, str]:
        data: dict[str, Any] = {
            "deck_name": self.deck_name,
            "model_name": self.model_name,
            "server_url": self.server_url,
        }
        if self.field_map:
            data["field_map"] = self.field_map
        return data


def _normalize_field_map(field_map: dict[str, str] | None) -> dict[str, str]:
    if not field_map:
        return {}

    normalized: dict[str, str] = {}
    for source_field, target_field in field_map.items():
        source_name = str(source_field).strip()
        target_name = str(target_field).strip()
        if source_name and target_name:
            normalized[source_name] = target_name
    return normalized


def load_config() -> AnkiConnectConfig | None:
    if not CONFIG_PATH.exists():
        return None

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config file: {CONFIG_PATH}")
    return AnkiConnectConfig.from_dict(data)


def save_config(config: AnkiConnectConfig) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_config(input_func=input) -> AnkiConnectConfig:
    existing = load_config()
    if existing is not None:
        return existing

    deck_name = input_func(f"Anki deck name [{DEFAULT_DECK_NAME}]: ").strip() or DEFAULT_DECK_NAME
    model_name = input_func(f"Anki note type [{DEFAULT_MODEL_NAME}]: ").strip() or DEFAULT_MODEL_NAME
    server_url = input_func(f"AnkiConnect URL [{DEFAULT_SERVER_URL}]: ").strip() or DEFAULT_SERVER_URL

    config = AnkiConnectConfig(deck_name=deck_name, model_name=model_name, server_url=server_url)
    save_config(config)
    return config


def _request(config: AnkiConnectConfig, action: str, params: dict[str, Any] | None = None) -> Any:
    payload = {"action": action, "version": 6, "params": params or {}}
    response = requests.post(config.server_url, json=payload, timeout=10, proxies=PROXIES)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data.get("result")


def health_check(config: AnkiConnectConfig) -> bool:
    try:
        _request(config, "version")
    except Exception:
        return False
    return True


def list_decks(config: AnkiConnectConfig) -> list[str]:
    result = _request(config, "deckNames")
    return [str(deck) for deck in result or []]


def list_models(config: AnkiConnectConfig) -> list[str]:
    result = _request(config, "modelNames")
    return [str(model) for model in result or []]


def get_model_fields(config: AnkiConnectConfig, model_name: str) -> list[str]:
    result = _request(config, "modelFieldNames", {"modelName": model_name})
    return [str(field) for field in result or []]


def _validate_anki_setup(config: AnkiConnectConfig) -> None:
    decks = list_decks(config)
    if config.deck_name not in decks:
        available = ", ".join(decks) if decks else "(no decks returned)"
        raise RuntimeError(
            f"Deck '{config.deck_name}' was not found in AnkiConnect. Available decks: {available}"
        )

    models = list_models(config)
    if config.model_name not in models:
        available = ", ".join(models) if models else "(no note types returned)"
        raise RuntimeError(
            f"Note type '{config.model_name}' was not found in AnkiConnect. Available note types: {available}"
        )

    available_fields = set(get_model_fields(config, config.model_name))
    mapping = _resolve_field_map(config, available_fields)
    if not mapping:
        available = ", ".join(sorted(available_fields)) if available_fields else "(no fields returned)"
        raise RuntimeError(
            "No note field mapping could be resolved. Add matching fields to the note type or set "
            f'"field_map" in {CONFIG_PATH}. Available fields: {available}'
        )

    missing_targets = sorted({target_field for target_field in mapping.values() if target_field not in available_fields})
    if missing_targets:
        available = ", ".join(sorted(available_fields)) if available_fields else "(no fields returned)"
        missing = ", ".join(missing_targets)
        raise RuntimeError(
            f"Note type '{config.model_name}' is missing mapped fields: {missing}. Available fields: {available}"
        )


def _resolve_field_map(config: AnkiConnectConfig, available_fields: set[str]) -> dict[str, str]:
    configured = _normalize_field_map(config.field_map)
    if configured:
        return configured

    return {field_name: field_name for field_name in CARD_FIELDS if field_name in available_fields}


def _build_note_fields(card: GeneratedCard, config: AnkiConnectConfig, available_fields: set[str]) -> dict[str, str]:
    mapping = _resolve_field_map(config, available_fields)
    if not mapping:
        return {}

    card_values = card.to_dict()
    note_fields: dict[str, str] = {}
    for card_field, note_field in mapping.items():
        if card_field not in card_values:
            continue
        value = card_values[card_field]
        if value or note_field in available_fields:
            note_fields[note_field] = value
    return note_fields


def add_card_to_anki(card: GeneratedCard, config: AnkiConnectConfig) -> bool:
    if not health_check(config):
        raise RuntimeError(
            f"AnkiConnect is unavailable at {config.server_url}. Start Anki and the AnkiConnect add-on first."
        )

    available_fields = set(get_model_fields(config, config.model_name))
    _validate_anki_setup(config)

    if not card.sentence_cloze or not card.sentence_cloze.strip():
        raise ValueError("Card sentence_cloze cannot be empty.")
    if not card.hint or not card.hint.strip():
        raise ValueError("Card hint cannot be empty.")
    if not card.meaning or not card.meaning.strip():
        raise ValueError("Card meaning cannot be empty.")

    fields = _build_note_fields(card, config, available_fields)
    if not fields:
        raise RuntimeError(
            "No Anki fields were populated. Check the note type fields or configure field_map in .ankiconnect_config."
        )

    note = {
        "deckName": config.deck_name,
        "modelName": config.model_name,
        "fields": fields,
        "options": {"allowDuplicate": False},
        "tags": ["voca"],
    }
    try:
        _request(config, "addNote", {"note": note})
    except RuntimeError as exc:
        error_msg = str(exc)
        debug_info = (
            f"\nDebug info:\n- Sentence cloze: {card.sentence_cloze[:50]}..."
            f"\n- Deck: {config.deck_name}\n- Model: {config.model_name}"
        )
        raise RuntimeError(f"Failed to create note in Anki: {error_msg}{debug_info}") from exc
    return True
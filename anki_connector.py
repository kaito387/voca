from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / ".ankiconnect_config"
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"
DEFAULT_DECK_NAME = "Default"
DEFAULT_MODEL_NAME = "Basic"
REQUIRED_FIELDS = {"Front", "Back", "Extra"}
PROXIES = {
    "http://": "socks5://127.0.0.1:7890",
    "https://": "socks5://127.0.0.1:7890",
}


@dataclass(slots=True)
class AnkiConnectConfig:
    deck_name: str = DEFAULT_DECK_NAME
    model_name: str = DEFAULT_MODEL_NAME
    server_url: str = DEFAULT_SERVER_URL

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnkiConnectConfig":
        return cls(
            deck_name=str(data.get("deck_name", DEFAULT_DECK_NAME)).strip() or DEFAULT_DECK_NAME,
            model_name=str(data.get("model_name", DEFAULT_MODEL_NAME)).strip() or DEFAULT_MODEL_NAME,
            server_url=str(data.get("server_url", DEFAULT_SERVER_URL)).strip() or DEFAULT_SERVER_URL,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "deck_name": self.deck_name,
            "model_name": self.model_name,
            "server_url": self.server_url,
        }


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

    fields = set(get_model_fields(config, config.model_name))
    missing_fields = REQUIRED_FIELDS.difference(fields)
    if missing_fields:
        available = ", ".join(sorted(fields)) if fields else "(no fields returned)"
        missing = ", ".join(sorted(missing_fields))
        raise RuntimeError(
            f"Note type '{config.model_name}' is missing required fields: {missing}. Available fields: {available}"
        )


def add_card_to_anki(front: str, back: str, extra: str, config: AnkiConnectConfig) -> bool:
    if not health_check(config):
        raise RuntimeError(
            f"AnkiConnect is unavailable at {config.server_url}. Start Anki and the AnkiConnect add-on first."
        )

    _validate_anki_setup(config)

    note = {
        "deckName": config.deck_name,
        "modelName": config.model_name,
        "fields": {
            "Front": front,
            "Back": back,
            "Extra": extra,
        },
        "options": {"allowDuplicate": False},
        "tags": ["voca"],
    }
    _request(config, "addNote", {"note": note})
    return True
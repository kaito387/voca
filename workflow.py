from __future__ import annotations

from anki_connector import AnkiConnectConfig, add_card_to_anki
from llm import GeneratedCard, generate_anki_card


def generate_and_submit(
    sentence: str,
    target: str,
    note: str | None,
    config: AnkiConnectConfig,
) -> GeneratedCard:
    card = generate_anki_card(sentence=sentence, target=target, note=note)
    add_card_to_anki(card=card, config=config)
    return card
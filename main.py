from __future__ import annotations

from anki_connector import add_card_to_anki, ensure_config
from llm import generate_anki_card


def _validate_sentence_and_target(sentence: str, target: str) -> None:
    if not sentence:
        raise ValueError("Sentence cannot be empty.")
    if not target:
        raise ValueError("Target cannot be empty.")


def main() -> None:
    config = ensure_config()

    print("Anki card generator ready. Type q to quit.\n")

    while True:
        sentence = input("Enter sentence (or 'q' to quit): ").strip()
        if sentence.lower() in {"q", "quit", "exit"}:
            break
        if not sentence:
            print("Sentence cannot be empty.\n")
            continue

        target = input("Enter target word/phrase: ").strip()
        if target.lower() in {"q", "quit", "exit"}:
            break

        try:
            _validate_sentence_and_target(sentence, target)
            card = generate_anki_card(sentence=sentence, target=target)
            add_card_to_anki(
                front=card["front"],
                back=card["back"],
                extra=card.get("extra", ""),
                config=config,
            )
        except Exception as exc:
            print(f"Error: {exc}\n")
            continue

        print("Card added to Anki.\n")


if __name__ == "__main__":
    main()
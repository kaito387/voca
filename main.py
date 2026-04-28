from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from anki_connector import (
    AnkiConnectConfig,
    DEFAULT_DECK_NAME,
    DEFAULT_MODEL_NAME,
    DEFAULT_SERVER_URL,
    load_config,
    save_config,
)
from workflow import generate_and_submit


class VocaWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("voca")
        self.root.minsize(760, 680)

        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.config = self._load_startup_config()
        self._build_ui()
        self._poll_results()

    def _load_startup_config(self) -> AnkiConnectConfig:
        try:
            loaded_config = load_config()
        except Exception:
            loaded_config = None
        return loaded_config or AnkiConnectConfig()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        card_frame = ttk.LabelFrame(container, text="Card input", padding=12)
        card_frame.grid(row=0, column=0, sticky="nsew")
        card_frame.columnconfigure(1, weight=1)

        ttk.Label(card_frame, text="Sentence").grid(row=0, column=0, sticky="nw", pady=(0, 8))
        self.sentence_text = tk.Text(card_frame, height=5, wrap="word")
        self.sentence_text.grid(row=0, column=1, sticky="nsew", pady=(0, 8))

        ttk.Label(card_frame, text="Target").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.target_var = tk.StringVar()
        ttk.Entry(card_frame, textvariable=self.target_var).grid(row=1, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(card_frame, text="Note / source (optional)").grid(row=2, column=0, sticky="w", pady=(0, 8))
        self.note_var = tk.StringVar()
        ttk.Entry(card_frame, textvariable=self.note_var).grid(row=2, column=1, sticky="ew", pady=(0, 8))

        anki_frame = ttk.LabelFrame(container, text="AnkiConnect settings", padding=12)
        anki_frame.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        anki_frame.columnconfigure(1, weight=1)

        self.deck_var = tk.StringVar(value=self.config.deck_name)
        self.model_var = tk.StringVar(value=self.config.model_name)
        self.server_var = tk.StringVar(value=self.config.server_url)

        ttk.Label(anki_frame, text="Deck name").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(anki_frame, textvariable=self.deck_var).grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(anki_frame, text="Note type").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(anki_frame, textvariable=self.model_var).grid(row=1, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(anki_frame, text="AnkiConnect URL").grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(anki_frame, textvariable=self.server_var).grid(row=2, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(
            anki_frame,
            text="Field map JSON (optional, card field -> note field)",
        ).grid(row=3, column=0, sticky="nw", pady=(0, 8))
        self.field_map_text = tk.Text(anki_frame, height=4, wrap="word")
        self.field_map_text.grid(row=3, column=1, sticky="ew", pady=(0, 8))
        if self.config.field_map:
            self.field_map_text.insert("1.0", json.dumps(self.config.field_map, ensure_ascii=False, indent=2))

        button_row = ttk.Frame(container)
        button_row.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        button_row.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(button_row, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

        self.submit_button = ttk.Button(button_row, text="Generate and add", command=self._submit)
        self.submit_button.grid(row=0, column=1, sticky="e", padx=(12, 0))

        ttk.Button(button_row, text="Quit", command=self.root.destroy).grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _parse_field_map(self) -> dict[str, str]:
        raw_value = self.field_map_text.get("1.0", "end").strip()
        if not raw_value:
            return {}

        parsed = json.loads(raw_value)
        if not isinstance(parsed, dict):
            raise ValueError("Field map must be a JSON object.")

        normalized: dict[str, str] = {}
        for source_field, target_field in parsed.items():
            source_name = str(source_field).strip()
            target_name = str(target_field).strip()
            if source_name and target_name:
                normalized[source_name] = target_name

        return normalized

    def _collect_config(self) -> AnkiConnectConfig:
        return AnkiConnectConfig(
            deck_name=self.deck_var.get().strip() or DEFAULT_DECK_NAME,
            model_name=self.model_var.get().strip() or DEFAULT_MODEL_NAME,
            server_url=self.server_var.get().strip() or DEFAULT_SERVER_URL,
            field_map=self._parse_field_map(),
        )

    def _set_busy(self, busy: bool) -> None:
        self.submit_button.configure(state="disabled" if busy else "normal")

    def _submit(self) -> None:
        sentence = self.sentence_text.get("1.0", "end").strip()
        target = self.target_var.get().strip()
        note = self.note_var.get().strip() or None

        if not sentence:
            messagebox.showerror("voca", "Sentence cannot be empty.")
            return
        if not target:
            messagebox.showerror("voca", "Target cannot be empty.")
            return

        try:
            config = self._collect_config()
        except Exception as exc:
            messagebox.showerror("voca", f"Invalid Anki settings: {exc}")
            return

        try:
            save_config(config)
        except Exception as exc:
            messagebox.showerror("voca", f"Failed to save config: {exc}")
            return

        self._set_busy(True)
        self.status_var.set("Generating card and sending to Anki...")

        worker = threading.Thread(
            target=self._run_submission,
            args=(sentence, target, note, config),
            daemon=True,
        )
        worker.start()

    def _run_submission(
        self,
        sentence: str,
        target: str,
        note: str | None,
        config: AnkiConnectConfig,
    ) -> None:
        try:
            card = generate_and_submit(sentence=sentence, target=target, note=note, config=config)
        except Exception as exc:  # pragma: no cover - UI thread boundary
            self.result_queue.put(("error", exc))
        else:
            self.result_queue.put(("success", card))

    def _poll_results(self) -> None:
        try:
            status, payload = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_results)
            return

        self._set_busy(False)
        if status == "error":
            error = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
            self.status_var.set("Failed")
            messagebox.showerror("voca", str(error))
        else:
            self.status_var.set("Card added to Anki.")
            messagebox.showinfo("voca", "Card added to Anki.")

        self.root.after(100, self._poll_results)


def main() -> None:
    root = tk.Tk()
    VocaWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
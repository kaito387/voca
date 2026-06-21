from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .anki_connector import (
    AnkiConnectConfig,
    DEFAULT_DECK_NAME,
    DEFAULT_MODEL_NAME,
    DEFAULT_SERVER_URL,
    load_config,
    save_config,
)
from .workflow import generate_and_submit

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="voca", version="0.2.0")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ConfigPayload(BaseModel):
    deck_name: str = DEFAULT_DECK_NAME
    model_name: str = DEFAULT_MODEL_NAME
    server_url: str = DEFAULT_SERVER_URL
    field_map: dict[str, str] | None = None


class GenerateRequest(BaseModel):
    target: str
    sentence: str | None = None
    note: str | None = None
    config: ConfigPayload | None = None


class GenerateResponse(BaseModel):
    status: str
    card: dict[str, str] | None = None


class ConfigResponse(BaseModel):
    deck_name: str
    model_name: str
    server_url: str
    field_map: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_config(payload: ConfigPayload | None) -> AnkiConnectConfig:
    if payload is None:
        return _load_or_default_config()
    return AnkiConnectConfig(
        deck_name=payload.deck_name.strip() or DEFAULT_DECK_NAME,
        model_name=payload.model_name.strip() or DEFAULT_MODEL_NAME,
        server_url=payload.server_url.strip() or DEFAULT_SERVER_URL,
        field_map=payload.field_map,
    )


def _load_or_default_config() -> AnkiConnectConfig:
    try:
        loaded = load_config()
    except Exception:
        loaded = None
    return loaded or AnkiConnectConfig()


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Return the saved AnkiConnect configuration (from disk)."""
    cfg = _load_or_default_config()
    return ConfigResponse(
        deck_name=cfg.deck_name,
        model_name=cfg.model_name,
        server_url=cfg.server_url,
        field_map=cfg.field_map,
    )


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_card(req: GenerateRequest) -> GenerateResponse:
    """Generate an Anki card from the target word/phrase and add it to Anki."""
    if not req.target.strip():
        raise HTTPException(status_code=400, detail="Target word cannot be empty.")

    config = _to_config(req.config)

    # Persist the config so future sessions remember the settings
    try:
        save_config(config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {exc}")

    try:
        card = generate_and_submit(
            sentence=req.sentence,
            target=req.target.strip(),
            note=req.note,
            config=config,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return GenerateResponse(status="ok", card=card.to_dict())


# ---------------------------------------------------------------------------
# Static files (must be mounted last so API routes take precedence)
# ---------------------------------------------------------------------------

@app.get("/favicon.ico")
async def serve_favicon():
    """Serve a simple SVG favicon (browsers request this by default)."""
    from fastapi.responses import Response
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">'
        '<stop offset="0%" stop-color="#7950f2"/>'
        '<stop offset="100%" stop-color="#d6336c"/>'
        '</linearGradient></defs>'
        '<rect width="32" height="32" rx="8" fill="url(#g)"/>'
        '<text x="16" y="23" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="20" fill="white">V</text>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/")
async def serve_index():
    """Serve the main HTML page."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    from fastapi.responses import HTMLResponse
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


def create_app() -> FastAPI:
    """Create and return the FastAPI application (useful for uvicorn factory)."""
    return app

"""LLM client via Ollama's OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_API_KEY = "ollama"

_ENV_LOADED = False


def _ensure_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    _ENV_LOADED = True


def get_base_url() -> str:
    _ensure_env()
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def get_model() -> str:
    _ensure_env()
    return os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def get_api_key() -> str:
    """Ollama does not need a real key; empty OPENAI_API_KEY in .env is OK."""
    _ensure_env()
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    return key or DEFAULT_API_KEY


def get_client() -> OpenAI:
    """OpenAI SDK pointed at Ollama (or any OpenAI-compatible endpoint)."""
    return OpenAI(base_url=get_base_url(), api_key=get_api_key())


def _parse_json_content(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Salvage: small models sometimes wrap JSON in prose or add trailing
        # text. Retry on the substring spanning the outermost braces.
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            return json.loads(text[start : end + 1])
        raise


def _ollama_extra_body() -> dict[str, Any]:
    """Ollama-specific tuning: keep the model warm and bound the context window."""
    extra: dict[str, Any] = {}
    keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "15m").strip()
    if keep_alive:
        extra["keep_alive"] = keep_alive
    num_ctx = os.environ.get("OLLAMA_NUM_CTX", "").strip()
    if num_ctx:
        try:
            extra["options"] = {"num_ctx": int(num_ctx)}
        except ValueError:
            pass
    return extra


def chat_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Request a JSON object from the configured model (Ollama by default).
    """
    client = get_client()
    model = get_model()
    logger.info("LLM request: model=%s base_url=%s", model, get_base_url())

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    extra_body = _ollama_extra_body()
    if extra_body:
        kwargs["extra_body"] = extra_body

    try:
        response = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("JSON mode failed (%s), retrying without response_format", exc)
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as retry_exc:
            raise RuntimeError(
                f"Ollama request failed ({get_base_url()}, model={model}). "
                "Is Ollama running? Try: ollama serve && ollama pull "
                f"{model}. Details: {retry_exc}"
            ) from retry_exc

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(
            f"Model '{model}' returned empty content. "
            f"Run: ollama pull {model}"
        )
    return _parse_json_content(content)

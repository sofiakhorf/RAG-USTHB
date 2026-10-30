"""Generation stage: turn retrieved passages into a grounded LLM answer.

This is the stage ``rag/retrieval/retriever.py`` has always pointed at in its
pipeline diagram (``rag.retrieval -> rag.generation``) but which nobody had
written. It talks to any **OpenAI-compatible** ``/chat/completions`` endpoint,
which covers OpenAI, Groq, Mistral, OpenRouter, Together and a local Ollama
server without a provider-specific SDK - so no new dependency is added and the
stdlib HTTP client is enough.

Configuration (all read from the environment; nothing is hardcoded)
-------------------------------------------------------------------
=================  =========================================================
``LLM_API_KEY``    Bearer token. The name matches the one already reserved
                   in ``.env.example`` (``# LLM_API_KEY=``).
``LLM_PROVIDER``   ``openai`` (default), ``groq``, ``mistral``, ``openrouter``
                   or ``ollama``. Only supplies defaults for the two below.
``LLM_MODEL``      Model id, e.g. ``gpt-4o-mini``.
``LLM_BASE_URL``   API root ending in ``/v1``. Override to point at a proxy,
                   a different vendor, or a local server.
``LLM_TIMEOUT``    Seconds to wait (default 60).
=================  =========================================================

Honesty rules
-------------
* The key is read from the environment at call time and is **never** logged,
  echoed into an error message, or written to the database.
* A network or provider failure raises :class:`GenerationError`; it is never
  silently swallowed and never replaced by invented text. Callers fall back to
  the extractive answer, which is *sourced* text rather than a guess.
* :func:`is_configured` is the single test for whether real generation is
  possible - the caller must not decide that by inspecting the key itself.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

__all__ = [
    "DEFAULTS",
    "GenerationError",
    "GenerationUnavailable",
    "LLMConfig",
    "build_prompt",
    "generate",
    "is_configured",
    "load_config",
]

logger = logging.getLogger(__name__)

#: Per-provider defaults: ``(base_url, model)``. ``{}`` means "unknown
#: provider" - the operator must then supply both explicitly, which is safer
#: than guessing a vendor and sending the question to the wrong company.
DEFAULTS = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-large-latest"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    # Ollama runs locally and needs no key at all.
    "ollama": ("http://localhost:11434/v1", "llama3.1"),
}

#: Providers that authenticate with a key.
KEYLESS_PROVIDERS = {"ollama"}


class GenerationError(Exception):
    """The generation stage failed: bad configuration, network or provider error."""


class GenerationUnavailable(GenerationError):
    """No LLM is configured, so generation cannot be attempted at all."""


@dataclass(frozen=True)
class LLMConfig:
    """Resolved provider settings.

    Attributes:
        provider: Lowercased provider id.
        api_key: Bearer token, or ``""`` for a keyless local server.
        model: Model id to request.
        base_url: API root ending in ``/v1``.
        timeout: Seconds to wait for the completion.
    """

    provider: str
    api_key: str
    model: str
    base_url: str
    timeout: int

    @property
    def endpoint(self) -> str:
        """The full ``/chat/completions`` URL."""
        return f"{self.base_url.rstrip('/')}/chat/completions"


def load_config() -> LLMConfig:
    """Read the LLM settings from the environment, applying provider defaults.

    Returns:
        An :class:`LLMConfig`. Unknown providers still resolve, but with empty
        ``base_url``/``model`` unless the operator set them, so a typo cannot
        silently point traffic at a real vendor.

    Note:
        Nothing here raises for missing values - callers decide whether a
        partial configuration is fatal, which is what lets the API serve an
        extractive answer when no LLM is set up.
    """
    provider = (os.environ.get("LLM_PROVIDER") or "openai").strip().lower()
    default_base, default_model = DEFAULTS.get(provider, ("", ""))

    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    base_url = (os.environ.get("LLM_BASE_URL") or "").strip() or default_base
    model = (os.environ.get("LLM_MODEL") or "").strip() or default_model

    raw_timeout = (os.environ.get("LLM_TIMEOUT") or "").strip()
    try:
        timeout = int(raw_timeout) if raw_timeout else 60
    except ValueError:
        timeout = 60

    return LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=timeout,
    )


def is_configured() -> bool:
    """Whether real LLM generation can be attempted.

    Returns:
        ``True`` when a model and a base URL are resolved and, unless the
        provider is keyless, an API key is present. ``False`` otherwise - which
        is the normal state of this deployment, and means the API serves the
        extractive answer.
    """
    config = load_config()

    if not config.model or not config.base_url:
        return False

    if config.provider in KEYLESS_PROVIDERS:
        return True

    return bool(config.api_key)


def build_prompt(messages: list[dict]) -> str:
    """Render messages into a single prompt string.

    Kept public so an operator can eyeball exactly what would be sent - the
    most reliable defence against a mis-assembled context - without making an
    API call.

    Args:
        messages: ``[{"role": ..., "content": ...}, ...]``.

    Returns:
        The messages joined with a blank line between roles.
    """
    return "\n\n".join(
        f"{m.get('role', 'user').upper()}:\n{m.get('content', '')}" for m in messages
    )


def _describe_error(exc: Exception) -> str:
    """Turn a urllib failure into a message that is useful but leaks no secret.

    ``urllib`` includes the request's full URL in ``HTTPError`` text. The URL
    carries no credential here (the key goes in a header), but the body from a
    provider can echo the key back on some errors, so only the status line is
    reported.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} from the LLM provider"
    return f"{type(exc).__name__}: {exc}"


def generate(messages: list[dict]) -> str:
    """Call the configured LLM and return its answer text.

    Args:
        messages: ``[{"role": ..., "content": ...}, ...]``; the first is the
            RAG system prompt from :mod:`rag.prompts.system`.

    Returns:
        The assistant's reply, stripped. Never empty.

    Raises:
        GenerationUnavailable: If no LLM is configured.
        GenerationError: On a network failure, a non-2xx response, or a
            response body that is not the expected JSON shape.

    Note:
        Temperature is pinned to ``0``. A grounded academic answer should be
        reproducible; sampling would make two identical questions return
        different dates, which is exactly the failure the prompt forbids.
    """
    config = load_config()

    if not is_configured():
        raise GenerationUnavailable(
            "No LLM is configured. Set LLM_API_KEY (and optionally "
            "LLM_PROVIDER / LLM_MODEL / LLM_BASE_URL), or leave it unset to "
            "serve the extractive answer instead."
        )

    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
    }

    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    request = urllib.request.Request(
        config.endpoint,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Do not read the body: some providers echo the Authorization header
        # back in their error payload.
        raise GenerationError(
            f"The LLM provider returned {_describe_error(exc)}."
        ) from exc
    except Exception as exc:
        raise GenerationError(
            f"Could not reach the LLM provider: {_describe_error(exc)}."
        ) from exc

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise GenerationError(
            f"The LLM response was not in the expected shape ({type(exc).__name__})."
        ) from exc

    if not isinstance(content, str) or not content.strip():
        raise GenerationError("The LLM returned an empty answer.")

    # Logged without the key or the prompt, so a deployment can see generation
    # is happening without the transcript landing in the log files.
    logger.info("LLM generation succeeded (provider=%s, model=%s)", config.provider, config.model)

    return content.strip()

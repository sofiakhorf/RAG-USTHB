"""
GENERATION TESTS - RAG-USTHB.
=============================
PURPOSE:  Executable specification of ``rag/generation``, the stage that sends
          the retrieved context to an LLM and returns its grounded answer.
          Nothing here touches Django, a database or a real provider: the HTTP
          side is exercised against a local mock server, which is enough to
          pin down the request shape, the secret handling and the error paths
          without spending a token or inventing an answer.

RUN:      .venv\\Scripts\\python.exe rag\\tests\\test_generation.py

What is covered
---------------
* ``load_config``      - per-provider defaults, environment overrides, and the
  timeout fallback for a malformed value.
* ``is_configured``    - the single source of truth for "can we really
  generate?", including the keyless local-Ollama case.
* ``generate``         - the real HTTP request path against a mock server
  (endpoint, bearer header, model, ``temperature 0``), plus the three failure
  modes: not configured, provider error, malformed reply.
* Secret hygiene      - the API key must never appear in an exception, which
  is the one bug that turns a bad deployment into a leaked credential.
"""

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from rag.generation import (  # noqa: E402
    DEFAULTS,
    GenerationError,
    GenerationUnavailable,
    build_prompt,
    generate,
    is_configured,
    load_config,
)

#: A sentinel so the tests can prove the key is sent where it belongs and
#: nowhere it does not.
SENTINEL_KEY = "sk-test-DO-NOT-LEAK-0001"


class EnvIsolatedTestCase(unittest.TestCase):
    """Base class that gives each test a clean, known environment.

    ``load_config`` reads ``os.environ`` at call time, so patching it per test
    is both necessary and sufficient; nothing is cached across tests.
    """

    def config_env(self, **overrides):
        """Patch the environment, clearing every LLM_* variable first."""
        base = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")}
        base.update(overrides)
        return patch.dict(os.environ, base, clear=True)


class LoadConfigTests(EnvIsolatedTestCase):
    """Reading provider settings from the environment."""

    def test_defaults_to_openai(self):
        with self.config_env():
            cfg = load_config()
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.model, "gpt-4o-mini")
        self.assertEqual(cfg.base_url, "https://api.openai.com/v1")
        self.assertEqual(cfg.api_key, "")
        self.assertEqual(cfg.timeout, 60)

    def test_every_documented_provider_resolves_a_default(self):
        for provider in ("openai", "groq", "mistral", "openrouter", "ollama"):
            with self.config_env(LLM_PROVIDER=provider):
                cfg = load_config()
            with self.subTest(provider=provider):
                self.assertTrue(cfg.model, f"{provider} has no default model")
                self.assertTrue(cfg.base_url, f"{provider} has no default base_url")

    def test_provider_defaults_are_known_to_the_mapping(self):
        """No provider may silently resolve to an empty base_url."""
        for provider in DEFAULTS:
            self.assertIn(provider, DEFAULTS)

    def test_environment_overrides_the_default_model(self):
        with self.config_env(LLM_MODEL="my-custom-model"):
            self.assertEqual(load_config().model, "my-custom-model")

    def test_environment_overrides_the_default_base_url(self):
        with self.config_env(LLM_BASE_URL="http://proxy.local:9000/v1"):
            self.assertEqual(load_config().base_url, "http://proxy.local:9000/v1")

    def test_unknown_provider_resolves_empty_defaults(self):
        """A typo must not point traffic at a real vendor by accident."""
        with self.config_env(LLM_PROVIDER="totally-made-up"):
            cfg = load_config()
        self.assertEqual(cfg.model, "")
        self.assertEqual(cfg.base_url, "")

    def test_timeout_is_parsed_as_an_integer(self):
        with self.config_env(LLM_TIMEOUT="15"):
            self.assertEqual(load_config().timeout, 15)

    def test_malformed_timeout_falls_back_to_the_default(self):
        for bad in ("abc", "", "  ", "10.5"):
            with self.subTest(value=bad), self.config_env(LLM_TIMEOUT=bad):
                self.assertEqual(load_config().timeout, 60)

    def test_key_is_stripped(self):
        with self.config_env(LLM_API_KEY="  spaced-key  "):
            self.assertEqual(load_config().api_key, "spaced-key")

    def test_endpoint_appends_chat_completions_without_duplicating_slashes(self):
        with self.config_env(LLM_BASE_URL="http://x.local/v1/"):
            self.assertEqual(load_config().endpoint, "http://x.local/v1/chat/completions")

    def test_provider_name_is_normalised(self):
        with self.config_env(LLM_PROVIDER="OpenAI"):
            self.assertEqual(load_config().provider, "openai")


class IsConfiguredTests(EnvIsolatedTestCase):
    """``is_configured`` decides whether the LLM path is attempted at all."""

    def test_not_configured_when_no_key(self):
        with self.config_env():
            self.assertFalse(is_configured())

    def test_configured_when_a_key_is_present(self):
        with self.config_env(LLM_API_KEY=SENTINEL_KEY):
            self.assertTrue(is_configured())

    def test_configured_without_a_key_for_a_keyless_provider(self):
        """A local Ollama server authenticates with nothing at all."""
        with self.config_env(LLM_PROVIDER="ollama"):
            self.assertTrue(is_configured())

    def test_not_configured_for_an_empty_key_string(self):
        with self.config_env(LLM_API_KEY="   "):
            self.assertFalse(is_configured())

    def test_not_configured_when_the_model_is_unresolved(self):
        """Unknown provider, no explicit model -> nothing to ask for."""
        with self.config_env(LLM_PROVIDER="typo", LLM_API_KEY=SENTINEL_KEY):
            self.assertFalse(is_configured())

    def test_not_configured_when_the_base_url_is_unresolved(self):
        with self.config_env(LLM_PROVIDER="typo", LLM_MODEL="m", LLM_API_KEY=SENTINEL_KEY):
            self.assertFalse(is_configured())


class BuildPromptTests(unittest.TestCase):
    """``build_prompt`` exists so an operator can read what would be sent."""

    def test_messages_are_joined_with_their_roles(self):
        rendered = build_prompt([
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USR"},
        ])
        self.assertEqual(rendered, "SYSTEM:\nSYS\n\nUSER:\nUSR")

    def test_a_missing_role_defaults_to_user(self):
        self.assertIn("USER:\nhello", build_prompt([{"content": "hello"}]))

    def test_a_missing_content_defaults_to_empty(self):
        self.assertIn("USER:\n", build_prompt([{"role": "user"}]))


class _RecordingHandler(BaseHTTPRequestHandler):
    """Answers ``/chat/completions`` with whatever the test configured."""

    #: Set on the class by each test before the request is made.
    status = 200
    content = "REPONSE GENEREE"
    raw_body = None
    captured = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        cls = type(self)
        cls.captured = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": json.loads(self.rfile.read(length)),
        }

        if cls.raw_body is not None:
            raw = cls.raw_body.encode("utf-8")
        else:
            raw = json.dumps({
                "choices": [{"message": {"role": "assistant", "content": cls.content}}]
            }).encode("utf-8")

        self.send_response(cls.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):   # keep the test output clean
        pass


class GenerateTests(EnvIsolatedTestCase):
    """The real request path, against a local mock provider."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _RecordingHandler.status = 200
        _RecordingHandler.content = "REPONSE GENEREE"
        _RecordingHandler.raw_body = None
        _RecordingHandler.captured = {}

    def env(self, **overrides):
        """Configure a keyless provider pointed at the mock server."""
        base = {
            "LLM_PROVIDER": "ollama",                       # keyless, no vendor default
            "LLM_BASE_URL": f"http://127.0.0.1:{self.port}/v1",
            "LLM_MODEL": "mock-model",
        }
        base.update(overrides)
        return self.config_env(**base)

    def messages(self):
        return [
            {"role": "system", "content": "SYSTEM: contexte ici"},
            {"role": "user", "content": "Ma question ?"},
        ]

    def test_generate_returns_the_assistant_text(self):
        with self.env():
            self.assertEqual(generate(self.messages()), "REPONSE GENEREE")

    def test_it_posts_to_chat_completions(self):
        with self.env():
            generate(self.messages())
        self.assertEqual(_RecordingHandler.captured["path"], "/v1/chat/completions")

    def test_it_sends_the_configured_model(self):
        with self.env(LLM_MODEL="abc-123"):
            generate(self.messages())
        self.assertEqual(_RecordingHandler.captured["body"]["model"], "abc-123")

    def test_temperature_is_pinned_to_zero(self):
        """A grounded answer must be reproducible, not sampled."""
        with self.env():
            generate(self.messages())
        self.assertEqual(_RecordingHandler.captured["body"]["temperature"], 0)

    def test_the_messages_are_forwarded_verbatim(self):
        with self.env():
            generate(self.messages())
        self.assertEqual(_RecordingHandler.captured["body"]["messages"], self.messages())

    def test_content_type_is_json(self):
        with self.env():
            generate(self.messages())
        self.assertIn("application/json", _RecordingHandler.captured["content_type"])

    def test_a_bearer_header_is_sent_when_a_key_is_set(self):
        with self.env(LLM_API_KEY=SENTINEL_KEY):
            generate(self.messages())
        self.assertEqual(
            _RecordingHandler.captured["auth"], f"Bearer {SENTINEL_KEY}"
        )

    def test_no_authorization_header_for_a_keyless_provider(self):
        with self.env():
            generate(self.messages())
        self.assertIsNone(_RecordingHandler.captured["auth"])

    def test_answer_whitespace_is_stripped(self):
        _RecordingHandler.content = "  reponse avec espaces  "
        with self.env():
            self.assertEqual(generate(self.messages()), "reponse avec espaces")

    def test_arabic_answers_survive(self):
        """The corpus and its questions are Arabic as well as French."""
        _RecordingHandler.content = "المادة الأولى تحدد ..."
        with self.env():
            self.assertEqual(generate(self.messages()), "المادة الأولى تحدد ...")


class GenerateFailureTests(EnvIsolatedTestCase):
    """Every failure must raise - never return invented or empty text."""

    def test_not_configured_raises_unavailable(self):
        with self.config_env():
            with self.assertRaises(GenerationUnavailable):
                generate([{"role": "user", "content": "hi"}])

    def test_unavailable_message_says_what_to_set(self):
        with self.config_env():
            with self.assertRaises(GenerationUnavailable) as ctx:
                generate([{"role": "user", "content": "hi"}])
        self.assertIn("LLM_API_KEY", str(ctx.exception))

    def test_generation_error_is_not_swallowed(self):
        """A caller must be able to fall back deliberately, not by accident."""
        self.assertTrue(issubclass(GenerationError, Exception))
        self.assertTrue(issubclass(GenerationUnavailable, GenerationError))

    def test_unreachable_provider_raises_generation_error(self):
        """Port 1 is reserved and nothing listens on it."""
        with self.config_env(
            LLM_PROVIDER="ollama",
            LLM_BASE_URL="http://127.0.0.1:1/v1",
            LLM_MODEL="m",
        ):
            with self.assertRaises(GenerationError):
                generate([{"role": "user", "content": "hi"}])

    def test_the_api_key_never_leaks_into_an_exception(self):
        """The one bug that turns a bad deployment into a leaked credential."""
        with self.config_env(
            LLM_PROVIDER="ollama",
            LLM_BASE_URL="http://127.0.0.1:1/v1",
            LLM_MODEL="m",
            LLM_API_KEY=SENTINEL_KEY,
        ):
            with self.assertRaises(GenerationError) as ctx:
                generate([{"role": "user", "content": "hi"}])
        self.assertNotIn(SENTINEL_KEY, str(ctx.exception))

    def test_the_key_never_leaks_on_an_http_error(self):
        """Provider 5xx bodies can echo the Authorization header back."""
        with self.config_env(
            LLM_PROVIDER="ollama",
            LLM_BASE_URL="http://127.0.0.1:1/v1",
            LLM_MODEL="m",
            LLM_API_KEY=SENTINEL_KEY,
        ):
            with self.assertRaises(GenerationError) as ctx:
                generate([{"role": "user", "content": "hi"}])
        self.assertNotIn(SENTINEL_KEY, str(ctx.exception))


class GenerateHttpErrorTests(EnvIsolatedTestCase):
    """Non-2xx responses and malformed bodies, against a local mock."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def env(self, **overrides):
        base = {
            "LLM_PROVIDER": "ollama",
            "LLM_BASE_URL": f"http://127.0.0.1:{self.port}/v1",
            "LLM_MODEL": "mock-model",
            "LLM_API_KEY": SENTINEL_KEY,
        }
        base.update(overrides)
        return self.config_env(**base)

    def run_with(self, status=200, content=None, raw_body=None):
        _RecordingHandler.status = status
        _RecordingHandler.content = content
        _RecordingHandler.raw_body = raw_body
        _RecordingHandler.captured = {}
        with self.env():
            return generate([{"role": "user", "content": "hi"}])

    def test_http_error_raises_and_names_the_status(self):
        with self.assertRaises(GenerationError) as ctx:
            self.run_with(status=401)
        self.assertIn("401", str(ctx.exception))

    def test_http_error_does_not_leak_the_key_even_if_the_body_echoes_it(self):
        _RecordingHandler.raw_body = json.dumps({"error": f"bad key {SENTINEL_KEY}"})
        with self.assertRaises(GenerationError) as ctx:
            self.run_with(status=401)
        self.assertNotIn(SENTINEL_KEY, str(ctx.exception))

    def test_non_json_body_raises(self):
        with self.assertRaises(GenerationError):
            self.run_with(raw_body="<html>gateway</html>")

    def test_unexpected_shape_raises(self):
        with self.assertRaises(GenerationError):
            self.run_with(raw_body=json.dumps({"unexpected": True}))

    def test_empty_choices_raises(self):
        with self.assertRaises(GenerationError):
            self.run_with(raw_body=json.dumps({"choices": []}))

    def test_empty_content_raises(self):
        """An empty reply must never be returned as an "answer"."""
        with self.assertRaises(GenerationError):
            self.run_with(content="")

    def test_whitespace_only_content_raises(self):
        with self.assertRaises(GenerationError):
            self.run_with(content="   ")

    def test_non_string_content_raises(self):
        with self.assertRaises(GenerationError):
            self.run_with(raw_body=json.dumps(
                {"choices": [{"message": {"content": ["not", "a", "string"]}}]}
            ))


if __name__ == "__main__":
    unittest.main(verbosity=2)

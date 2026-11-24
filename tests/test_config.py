"""Check local credential loading and environment precedence without network calls."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matagent.assistant.config import configured_provider


class ModelConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "model.json"
        self.path.write_text(json.dumps({
            "provider": "deepseek",
            "api_key": "test-only-local-credential",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-pro",
            "reasoning_effort": "low",
        }), encoding="utf-8")

    @patch.dict("os.environ", {}, clear=True)
    def test_local_config_is_used(self):
        provider = configured_provider(self.path)
        self.assertEqual(provider.api_key, "test-only-local-credential")
        self.assertEqual(provider.model, "deepseek-v4-pro")
        self.assertEqual(provider.reasoning_effort, "low")

    @patch.dict("os.environ", {
        "OPENAI_API_KEY": "test-only-environment-credential",
        "OPENAI_MODEL": "test-model",
        "OPENAI_BASE_URL": "https://example.invalid/v1",
    }, clear=True)
    def test_environment_credentials_use_their_own_endpoint(self):
        provider = configured_provider(self.path)
        self.assertEqual(provider.api_key, "test-only-environment-credential")
        self.assertEqual(provider.base_url, "https://example.invalid/v1")

    @patch.dict("os.environ", {}, clear=True)
    def test_malformed_file_error_does_not_echo_its_contents(self):
        self.path.write_text('{"api_key":"test-secret",', encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            configured_provider(self.path)
        self.assertNotIn("test-secret", str(caught.exception))

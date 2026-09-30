"""Provider auto-discovery tests (offline: fake environment
variables, a fake opencode config, and a mocked catalog
fetcher - no real API calls, no real keys)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import environment.provider_discovery as pd
from environment.config import Config
from environment.journal import Journal
from environment.providers import ProviderStore


def make_store(tmp):
    config = Config(tmp)
    config.ensure_dirs()
    journal = Journal(config.journal_path)
    return ProviderStore(config.providers_path,
                         journal), config


FAKE_OC_CONFIG = """{
  // opencode-style config with comments
  "provider": {
    "nvidia": {
      "name": "NVIDIA NIM",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://integrate.api.nvidia.com/v1",
        "apiKey": "nv-fake-key-1234567890"
      },
      "models": {
        "z-ai/glm-5.3": {
          "name": "GLM 5.3 (NVIDIA)",
          "limit": { "context": 1000000, "output": 128000 }
        },
        "nvidia/nemotron-3": {
          "name": "Nemotron 3",
          "limit": { "context": 256000, "output": 16384 }
        }
      }
    },
    "custom-gw": {
      "name": "Custom Gateway",
      "options": {
        "baseURL": "https://gw.example.com/v1",
        "apiKey": "gw-fake-key-1234567890"
      },
      "models": {
        "m-1": { "name": "Model One" }
      }
    }
  }
}
"""


class TestParsing(unittest.TestCase):
    def test_jsonc_stripping(self):
        stripped = pd._strip_jsonc(FAKE_OC_CONFIG)
        # comments removed, JSON parses
        cfg = json.loads(stripped)
        self.assertIn("nvidia",
                      cfg["provider"])

    def test_jsonc_string_with_slashes(self):
        text = ('{"url": "https://x/y", '
                '"c": "a \\" b /* not a comment */"}')
        stripped = pd._strip_jsonc(text)
        cfg = json.loads(stripped)
        self.assertEqual(cfg["url"], "https://x/y")

    def test_read_opencode_providers(self):
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "opencode.jsonc"
        p.write_text(FAKE_OC_CONFIG, encoding="utf-8")
        providers = pd.read_opencode_providers(p)
        self.assertIn("nvidia", providers)
        self.assertEqual(
            providers["nvidia"]["base_url"],
            "https://integrate.api.nvidia.com/v1")
        self.assertEqual(
            list(providers["nvidia"]["models"])[0],
            "z-ai/glm-5.3")
        self.assertEqual(
            providers["nvidia"]["models"][
                "z-ai/glm-5.3"]["context"], 1000000)
        self.assertTrue(providers["nvidia"][
                            "has_config_key"])


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store, self.config = make_store(self.tmp)
        # isolate from the real user environment
        self._saved = {
            k: os.environ.get(k) for k in
            ("NVIDIA_API_KEY", "OPENAI_API_KEY",
             "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
             "GROQ_API_KEY", "TOGETHER_API_KEY")}
        for k in self._saved:
            os.environ.pop(k, None)
        # point the parser at a fake config
        self._oc_path = Path(self.tmp) / "oc.jsonc"
        self._oc_path.write_text(
            FAKE_OC_CONFIG, encoding="utf-8")
        self._orig_path = pd._opencode_config_path
        pd._opencode_config_path = \
            lambda: self._oc_path

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        pd._opencode_config_path = self._orig_path
        for name in ("nvidia", "custom-gw"):
            try:
                self.store.get_api_key and None
                import keyring
                keyring.delete_password(
                    "veritas-environment", name)
            except Exception:
                pass

    def test_env_key_discovery_prefers_well_known(self):
        os.environ["NVIDIA_API_KEY"] = \
            "nv-env-fake-key-123456789"
        # offline: mock the live catalog fetch
        pd.fetch_model_catalog = \
            lambda base, key, timeout=25: [
                "z-ai/glm-5.3",
                "nvidia/nemotron-3",
                "extra/model-x"]
        out = pd.autodiscover(self.store)
        names = [e["provider"]
                 for e in out["discovered"]]
        self.assertIn("nvidia", names)
        entry = next(e for e in out["discovered"]
                     if e["provider"] == "nvidia")
        self.assertEqual(entry["key_source"], "env")
        self.assertEqual(entry["models"], 3)
        # config key fallback never used the env key's config
        prov = self.store.config["providers"][
            "nvidia"]
        self.assertEqual(len(prov["model_ids"]), 3)
        # display names merged from the config
        self.assertEqual(
            prov["model_info"]["z-ai/glm-5.3"][
                "name"],
            "GLM 5.3 (NVIDIA)")

    def test_default_binding_prefers_nvidia_config_order(self):
        os.environ["NVIDIA_API_KEY"] = \
            "nv-env-fake-key-123456789"
        os.environ["OPENAI_API_KEY"] = \
            "oa-env-fake-key-123456789"
        pd.fetch_model_catalog = \
            lambda base, key, timeout=25: ["m-a", "m-b"]
        out = pd.autodiscover(self.store)
        # NVIDIA is well-known and its config's first model
        # (the user's own preference order) wins
        self.assertEqual(
            out["default_binding"]["provider"],
            "nvidia")
        self.assertEqual(
            out["default_binding"]["model_id"],
            "z-ai/glm-5.3")

    def test_config_key_fallback(self):
        # no env var: the fake opencode config's key is used
        pd.fetch_model_catalog = \
            lambda base, key, timeout=25: ["m-1"]
        out = pd.autodiscover(self.store)
        names = [e["provider"]
                 for e in out["discovered"]]
        self.assertIn("nvidia", names)
        self.assertIn("custom-gw", names)
        nvidia = next(e for e in out["discovered"]
                      if e["provider"] == "nvidia")
        self.assertEqual(nvidia["key_source"],
                         "opencode-config")

    def test_no_key_no_discovery(self):
        # no env vars, config has no keys -> nothing registered
        self._oc_path.write_text(json.dumps({
            "provider": {
                "keyless": {
                    "options": {"baseURL":
                                "https://x/v1"},
                    "models": {"m": {}}
                }
            }
        }), encoding="utf-8")
        pd.fetch_model_catalog = \
            lambda base, key, timeout=25: []
        out = pd.autodiscover(self.store)
        self.assertEqual(out["discovered"], [])
        self.assertEqual(out["refreshed"], [])

    def test_idempotent_refresh(self):
        os.environ["NVIDIA_API_KEY"] = \
            "nv-env-fake-key-123456789"
        pd.fetch_model_catalog = \
            lambda base, key, timeout=25: ["m-a"]
        pd.autodiscover(self.store)
        out = pd.autodiscover(self.store)
        self.assertEqual(out["discovered"], [])
        self.assertTrue(any(
            e["provider"] == "nvidia"
            for e in out["refreshed"]))

    def test_catalog_failure_falls_back_to_config(self):
        os.environ["NVIDIA_API_KEY"] = \
            "nv-env-fake-key-123456789"
        pd.fetch_model_catalog = \
            lambda base, key, timeout=25: []
        out = pd.autodiscover(self.store)
        entry = next(e for e in out["discovered"]
                     if e["provider"] == "nvidia")
        self.assertFalse(entry["live_catalog"])
        self.assertEqual(entry["models"], 2)


if __name__ == "__main__":
    unittest.main()

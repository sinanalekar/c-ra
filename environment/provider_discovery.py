"""Provider auto-discovery.

CYR@ finds usable providers from (in priority order):
1. well-known environment variables (NVIDIA_API_KEY, ...),
2. the user's opencode configuration (provider blocks with
   base URLs, model ids, display names, and context limits),
3. the provider's own live /models catalog (the definitive
   availability list).

API keys come from the environment variable first, then the
opencode config as a fallback; either way the key is stored
immediately in the OS credential vault (keyring) and NEVER in
any config file, journal, or log. The discovery itself is
journaled without the key."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path


# well-known OpenAI-compatible providers and their env vars
WELL_KNOWN = {
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url":
            "https://integrate.api.nvidia.com/v1",
        "env": ("NVIDIA_API_KEY",
                "NVIDIA_NIM_API_KEY"),
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env": ("OPENAI_API_KEY",),
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "env": ("OPENROUTER_API_KEY",),
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "env": ("DEEPSEEK_API_KEY",),
    },
    "groq": {
        "label": "Groq",
        "base_url":
            "https://api.groq.com/openai/v1",
        "env": ("GROQ_API_KEY",),
    },
    "together": {
        "label": "Together",
        "base_url": "https://api.together.xyz/v1",
        "env": ("TOGETHER_API_KEY",),
    },
}


def _opencode_config_path() -> Path:
    home = Path.home()
    for cand in (
            home / ".config" / "opencode" /
            "opencode.jsonc",
            home / ".config" / "opencode" /
            "opencode.json"):
        if cand.is_file():
            return cand
    return home / ".config" / "opencode" / \
        "opencode.jsonc"


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments so JSONC parses as JSON."""
    out = []
    i = 0
    n = len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"' and (i == 0 or text[i - 1] != "\\"):
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and \
                text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and \
                text[i + 1] == "*":
            i += 2
            while i + 1 < n and \
                    not (text[i] == "*" and
                         text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def read_opencode_providers(
        path: Path | None = None) -> dict:
    """Parse the user's opencode config (read-only) into
    provider records: {id: {base_url, models: {id: {name,
    context, output}}, has_key}}. Never returns the API key."""
    p = path or _opencode_config_path()
    if not p.is_file():
        return {}
    try:
        raw = p.read_text(encoding="utf-8",
                          errors="replace")
        cfg = json.loads(_strip_jsonc(raw))
    except (json.JSONDecodeError, OSError):
        return {}
    providers = cfg.get("provider") or {}
    out = {}
    for pid, block in providers.items():
        if not isinstance(block, dict):
            continue
        options = block.get("options") or {}
        base_url = options.get("baseURL") or \
            options.get("base_url") or ""
        if not base_url:
            continue
        models = {}
        for mid, m in (block.get("models")
                       or {}).items():
            if not isinstance(m, dict):
                models[mid] = {"name": mid}
                continue
            limit = m.get("limit") or {}
            models[mid] = {
                "name": m.get("name") or mid,
                "context": limit.get("context"),
                "output": limit.get("output"),
            }
        out[pid] = {
            "label": block.get("name") or pid,
            "base_url": base_url,
            "models": models,
            "has_config_key":
                bool(options.get("apiKey")),
        }
    return out


def _opencode_key_for(pid: str) -> str | None:
    """Fallback only: the key from the opencode config (goes
    straight to the vault, never persisted by CYR@)."""
    p = _opencode_config_path()
    if not p.is_file():
        return None
    try:
        raw = p.read_text(encoding="utf-8",
                          errors="replace")
        cfg = json.loads(_strip_jsonc(raw))
        block = (cfg.get("provider")
                 or {}).get(pid) or {}
        key = (block.get("options")
               or {}).get("apiKey") or ""
        if isinstance(key, str) and len(key) > 8:
            return key
    except (json.JSONDecodeError, OSError):
        pass
    return None


def fetch_model_catalog(base_url: str,
                        api_key: str,
                        timeout: int = 25) -> list:
    """Live model discovery via the provider's /models
    endpoint (OpenAI-compatible). Returns [] on failure - the
    caller falls back to config-declared models."""
    try:
        req = urllib.request.Request(
            base_url.rstrip("/") + "/models",
            headers={
                "Authorization": "Bearer " + api_key,
                "User-Agent": "CYRA/1.0",
            })
        with urllib.request.urlopen(
                req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        ids = []
        for m in data.get("data", []):
            if isinstance(m, dict) and m.get("id"):
                ids.append(m["id"])
        return sorted(set(ids))
    except Exception:
        return []


def autodiscover(store, journal=None) -> dict:
    """Register every discoverable provider. Idempotent:
    existing providers are refreshed (models + key), never
    duplicated. Returns a discovery summary (no secrets)."""
    oc_providers = read_opencode_providers()
    found = {}
    # 1. well-known providers with env-var keys
    for pid, spec in WELL_KNOWN.items():
        key = next(
            (os.environ[v] for v in spec["env"]
             if os.environ.get(v)), None)
        oc = oc_providers.get(pid)
        base_url = (oc or {}).get(
            "base_url") or spec["base_url"]
        label = (oc or {}).get(
            "label") or spec["label"]
        if not key:
            # no env key: try the opencode config key
            key = _opencode_key_for(pid) \
                if (oc or {}).get("has_config_key") \
                else None
        if not key:
            continue
        found[pid] = {
            "label": label, "base_url": base_url,
            "key": key,
            "source": "env" if os.environ.get(
                spec["env"][0]) else
                "opencode-config",
            "config_models": (oc or {}).get(
                "models", {}),
        }
    # 2. opencode providers beyond the well-known set
    for pid, oc in oc_providers.items():
        if pid in found:
            continue
        key = _opencode_key_for(pid)
        if not key:
            continue
        found[pid] = {
            "label": oc["label"],
            "base_url": oc["base_url"],
            "key": key, "source": "opencode-config",
            "config_models": oc["models"],
        }

    summary = {"discovered": [], "refreshed": []}
    for pid, info in found.items():
        # register (or refresh) the provider record
        existing = pid in store.config[
            "providers"]
        store.config["providers"][pid] = {
            "name": pid,
            "base_url": info["base_url"],
            "api_format": "openai",
            "model_ids": [],
            "disabled": False,
        }
        # live model discovery (definitive list)
        catalog = fetch_model_catalog(
            info["base_url"], info["key"])
        # merge: catalog (availability) + config (names)
        model_ids = catalog or \
            list(info["config_models"].keys())
        model_info = dict(info["config_models"])
        for mid in catalog:
            model_info.setdefault(
                mid, {"name": mid})
        store.config["providers"][pid][
            "model_ids"] = model_ids
        store.config["providers"][pid][
            "model_info"] = model_info
        # store the key in the OS vault immediately
        key_rec = store.store_api_key(pid,
                                      info["key"])
        store._save()
        entry = {
            "provider": pid,
            "label": info["label"],
            "key_source": info["source"],
            "key_stored": key_rec.get("stored",
                                      False),
            "models": len(model_ids),
            "live_catalog": bool(catalog),
        }
        summary[
            "refreshed" if existing else
            "discovered"].append(entry)
        if journal:
            journal.append(
                "provider_discovered",
                provider=pid,
                key_source=info["source"],
                models=len(model_ids),
                live_catalog=bool(catalog),
                key_stored=key_rec.get(
                    "stored", False))

    # 3. sensible default bindings when nothing is configured:
    #    route the core roles to the best discovered model
    if found and not any(
            store.config[
                "role_bindings"].values()):
        best = _pick_default(found, store)
        if best:
            for role in ("coordinator", "planner",
                         "reasoning", "coding",
                         "research", "browser",
                         "terminal", "reviewer",
                         "report_writer"):
                store.config["role_bindings"][
                    role] = best
            store._save()
            if journal:
                journal.append(
                    "roles_auto_bound",
                    provider=best["provider"],
                    model_id=best["model_id"])
            summary["default_binding"] = best
    return summary


def _pick_default(found: dict,
                  store) -> dict | None:
    """Default binding: well-known providers first (the
    user's environment defines the preference - e.g. NVIDIA),
    then any other discovered provider. Within a provider the
    user's opencode-config model order wins (their own
    preference, e.g. GLM 5.3 first), else the catalog's first
    model."""
    order = list(WELL_KNOWN) + sorted(
        p for p in found if p not in WELL_KNOWN)
    for pid in order:
        if pid not in found:
            continue
        info = found[pid]
        pref = list(info["config_models"].keys())
        if pref:
            mid = pref[0]
            return {
                "provider": pid,
                "model_id": mid,
                "display":
                    info["config_models"][mid].get(
                        "name", mid)}
        ids = (store.config["providers"]
               .get(pid, {})
               .get("model_ids")) or []
        if ids:
            return {"provider": pid,
                    "model_id": ids[0],
                    "display": ids[0]}
    return None

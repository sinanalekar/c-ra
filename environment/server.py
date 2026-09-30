"""Server entry: localhost-only uvicorn launcher. Imports the
app factory directly (no string imports - keeps the PyInstaller
sidecar working). Provider auto-discovery (env-var keys, the
opencode config, live /models catalogs) runs once at startup."""
from __future__ import annotations

import uvicorn

from .app import Environment, create_app
from .version import PRODUCT_NAME


def build_app():
    """Create the app + run provider discovery once (env-var
    API keys like NVIDIA_API_KEY, the user's opencode config,
    and each provider's live /models catalog)."""
    env = Environment()
    app = create_app(env)
    from .provider_discovery import autodiscover
    try:
        env.discovery = autodiscover(
            env.providers, env.journal)
    except Exception as e:
        env.discovery = {"error": repr(e)[:300]}
    return app


def main():
    uvicorn.run(build_app(), host="127.0.0.1",
                port=8765, log_level="info")


if __name__ == "__main__":
    main()

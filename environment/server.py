"""Server entry: localhost-only uvicorn launcher. Imports the
app factory directly (no string imports - keeps the PyInstaller
sidecar working). The API comes up IMMEDIATELY; provider
auto-discovery runs in the background so the UI is never
blocked behind catalog fetches."""
from __future__ import annotations

import threading

import uvicorn

from .app import Environment, create_app
from .version import PRODUCT_NAME


def build_app():
    """Create the app; discovery runs in a background thread
    once the server is listening (env-var API keys like
    NVIDIA_API_KEY, the user's opencode config, and each
    provider's live /models catalog)."""
    env = Environment()
    app = create_app(env)

    @app.on_event("startup")
    def _background_discovery():
        def run():
            from .provider_discovery import \
                autodiscover
            try:
                env.discovery = autodiscover(
                    env.providers, env.journal)
            except Exception as e:
                env.discovery = {"error":
                                 repr(e)[:300]}
        threading.Thread(
            target=run, daemon=True).start()
    return app


def main():
    uvicorn.run(build_app(), host="127.0.0.1",
                port=8765, log_level="info")


if __name__ == "__main__":
    main()

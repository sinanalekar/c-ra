"""Server entry: localhost-only uvicorn launcher. Imports the
app factory directly (no string imports - keeps the PyInstaller
sidecar working)."""
from __future__ import annotations

import uvicorn

from .app import create_app
from .version import PRODUCT_NAME


def main():
    uvicorn.run(create_app(), host="127.0.0.1",
                port=8765, log_level="info")


if __name__ == "__main__":
    main()

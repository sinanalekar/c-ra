"""Server entry: localhost-only uvicorn launcher."""
from __future__ import annotations

import uvicorn


def main():
    uvicorn.run(
        "environment.app:create_app",
        factory=True, host="127.0.0.1", port=8765,
        log_level="info")


if __name__ == "__main__":
    main()

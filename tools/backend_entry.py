"""PyInstaller entry for the packaged backend sidecar: the
local research server, loopback-only."""
from environment.server import main

if __name__ == "__main__":
    main()

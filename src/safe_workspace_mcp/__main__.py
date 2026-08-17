"""python -m safe_workspace_mcp <config.toml>"""

from __future__ import annotations

import sys

from .config import load_config
from .server import build_server


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m safe_workspace_mcp <config.toml>", file=sys.stderr)
        raise SystemExit(2)
    config = load_config(sys.argv[1])
    server = build_server(config)
    server.run()  # stdio


if __name__ == "__main__":
    main()

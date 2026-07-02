"""Supervisor-friendly launcher: imports build_app and runs uvicorn."""

import uvicorn

from vision_mcp.config import load_config
from vision_mcp.server import build_app


def main() -> None:
    cfg = load_config()
    app = build_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
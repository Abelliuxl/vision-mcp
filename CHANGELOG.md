# Changelog

## v0.2.1 (2026-07-03)

Config location + Python interpreter alignment.

- **Move config to project root**: dropped `~/.config/vision-mcp/.env` (which conflicts across machines and tools), use `./.env` in this repo instead (mode 600, gitignored). `proxy/vision_proxy.py` resolves `ENV_FILE` relative to its own location; `install.sh` copies `.env.example` into `./.env`.
- **Integrate `uv`**: added `pyproject.toml` so `uv sync` builds a project-local `.venv` (currently Python 3.13). Client config now uses `uv run --project <repo> python proxy/vision_proxy.py` instead of relying on whatever `python3` the OS finds — sidesteps macOS's stripped-down system Python SSL CA path.
- **Verified end-to-end**: `uv run python proxy/test_vision_proxy.py` exits 0 (4 OK lines); a real `describe_image` round-trip to Doubao Seed 2.0 Mini via the proxy completes in ~2.4 s and returns the expected description.

## v0.2.0 (2026-07-03)

**BREAKING**: replaced the server-mode implementation with a single-file stdio MCP proxy.

- Removed: `vision_mcp/` package (FastMCP server, Starlette app, bearer auth, image decode, Ark HTTP client, three tools).
- Removed: `tests/` (45 server-mode tests).
- Removed: `deploy/` (nginx config, supervisor program, install.sh for server94).
- Removed: `pyproject.toml` + `uv.lock` (no longer needed; pure stdlib).
- Added: `proxy/vision_proxy.py` (single file, ~300 lines, pure stdlib).
- Added: `proxy/test_vision_proxy.py` (smoke test, no pytest).
- Added: `install.sh` (creates `~/.config/vision-mcp/.env` with mode 600).
- Updated: `README.md` for local-only deployment.

The server94 deployment has been uninstalled (vision-mcp supervisor program + nginx `/mcp` location removed; `/srv/vision-mcp`, `/etc/vision-mcp`, `/var/log/vision-mcp` deleted).

## v0.1.0 (2026-07-03)

Initial public release. Remote MCP server at `https://liuxl.com.cn/mcp`, backed by FastMCP + Starlette + Bearer token auth. Superseded by v0.2.0.
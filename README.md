# vision-mcp

A remote MCP server that exposes three vision tools (`ocr_image`, `describe_image`, `answer_image`) backed by Doubao Seed 2.0 Mini on Volcano Ark.

Endpoint: `https://vision.liuxl.com.cn/mcp` (single-user, Bearer-token auth).

See `docs/superpowers/specs/2026-07-03-vision-mcp-design.md` for the full design spec.

## Quick start (local dev)

```bash
git clone https://github.com/Abelliuxl/vision-mcp
cd vision-mcp
uv sync
cp .env.example .env
# fill in ARK_API_KEY in .env
uv run pytest
uv run python -m vision_mcp.server
```

## Deploy

See `deploy/install.sh`. Run on `server94`:

```bash
sudo -E bash deploy/install.sh
```

## License

MIT

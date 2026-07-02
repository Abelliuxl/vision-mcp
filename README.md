# vision-mcp

A **single-file, pure-Python-stdlib** stdio MCP server exposing three vision tools (`ocr_image`, `describe_image`, `answer_image`) backed by **Doubao Seed 2.0 Mini** on Volcano Ark.

No remote server is required. The proxy reads local image files passed by the LLM and forwards them directly to Ark over HTTPS.

## Quick start

1. Install once (creates the config directory and a placeholder `.env`):

   ```bash
   ./install.sh
   # then edit ~/.config/vision-mcp/.env and set ARK_API_KEY
   ```

2. Configure your MCP client (Cursor / Trae / Claude Code / etc.) with the stdio command:

   ```json
   {
     "mcpServers": {
       "vision": {
         "command": "python3",
         "args": ["/absolute/path/to/vision-mcp/proxy/vision_proxy.py"]
       }
     }
   }
   ```

3. From the LLM, call any of the three tools with `image_path: "/Users/you/screenshot.png"`.

## Tools

| Tool | Args | What it does |
|---|---|---|
| `ocr_image` | `image_path` (req), `lang` (auto\|zh\|en, default auto) | Extract text from the image verbatim. |
| `describe_image` | `image_path` (req), `detail` (short\|medium\|long, default medium) | Describe the image objectively. |
| `answer_image` | `image_path` (req), `question` (req), `context` (opt) | Answer a question grounded in the image. |

Image file is read once, validated (magic-byte MIME check, 8 MiB cap), base64-encoded, and sent to Ark. **Never written to disk by the proxy.**

## Configuration

`~/.config/vision-mcp/.env` (`chmod 600`):

```
ARK_API_KEY=<your-doubao-ark-key>
ARK_BASE_URL=https://ark.cn-beijing.volces.com   (default)
ARK_MODEL=doubao-seed-2-0-mini-260215            (default)
```

`ARK_API_KEY` and `ARK_BASE_URL` / `ARK_MODEL` can also be set via environment variables, which take precedence over the file.

## Tests

```bash
python3 proxy/test_vision_proxy.py
```

Drives the proxy as a subprocess; asserts initialize, tools/list, and a tool-call attempt (which fails upstream with the fake API key, by design).

## Requirements

- Python 3.8 or newer (no third-party deps).
- Network access to `ark.cn-beijing.volces.com:443` from the machine running the proxy.
- An Ark API key from <https://www.volcengine.com/>.

## Transport

- **Stdin**: supports both **LSP/MCP-style `Content-Length` framing** and **line-delimited JSON** (auto-detected per message).
- **Stdout**: line-delimited JSON-RPC 2.0 responses (one JSON object per line).
- **Stderr**: human-readable logs only — never pollutes the JSON-RPC stream.

## Security

- API key is read from `~/.config/vision-mcp/.env` with mode 600; never logged.
- Image bytes are read once into memory and freed; never persisted, never echoed.
- Logs go to **stderr only**; stdout is reserved for JSON-RPC.

## License

MIT. See [LICENSE](LICENSE).
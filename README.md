# vision-mcp

A **single-file, pure-Python-stdlib** stdio MCP server exposing three vision tools (`ocr_image`, `describe_image`, `answer_image`) backed by **Doubao Seed 2.0 Mini** on Volcano Ark.

No remote server is required. The proxy reads local image files passed by the LLM and forwards them directly to Ark over HTTPS. The LLM **never sees** the base64 payload.

## Quick start

1. Install once (creates a `.venv` and a `.env` placeholder):

   ```bash
   uv sync
   ./install.sh
   # then edit ./.env and set ARK_API_KEY
   ```

2. Configure your MCP client (Cursor / Trae / Claude Code / etc.):

   ```json
   {
     "mcpServers": {
       "vision": {
         "command": "uv",
         "args": [
           "run", "--project", "<abs-path-to-this-repo>",
           "python", "<abs-path-to-this-repo>/proxy/vision_proxy.py"
         ]
       }
     }
   }
   ```

   Replace `<abs-path-to-this-repo>` with the absolute path of this directory
   (e.g. `/Users/liuxiaoliang/Workplace/vision-mcp`). Using `uv run` keeps
   Python and CA certificates managed by uv, which avoids macOS system-Python
   SSL issues.

3. From the LLM, call any of the three tools with `image_path: "/Users/you/screenshot.png"`.

### Verify the install

The fastest way to confirm everything works before wiring a client:

```bash
uv run python - <<'EOF'
import subprocess, json, base64, struct, zlib, sys
from io import BytesIO

# tiny 4x1 PNG (red), generated in pure stdlib
def chunk(t, d):
    return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
sig = b'\x89PNG\r\n\x1a\n'
ihdr = struct.pack('>IIBBBBB', 4, 1, 8, 2, 0, 0, 0)
idat = zlib.compress(b'\x00' + b'\xff\x00\x00'*4)
png = sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')
with open('/tmp/_v.png', 'wb') as f: f.write(png)

repo = '/Users/liuxiaoliang/Workplace/vision-mcp'
proc = subprocess.Popen(
    ['uv', 'run', '--project', repo, 'python', f'{repo}/proxy/vision_proxy.py'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
proc.stdin.write((json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'verify','version':'0'}}})+'\n').encode()); proc.stdin.flush(); print('init:', proc.stdout.readline().decode().strip()[:120])
proc.stdin.write((json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'describe_image','arguments':{'image_path':'/tmp/_v.png','detail':'short'}}})+'\n').encode()); proc.stdin.flush()
out = proc.stdout.readline().decode().strip()
print('describe_image result:', out[:300])
proc.stdin.close(); proc.wait(timeout=5)
EOF
```

Expected: the description text from Doubao (e.g. "A small red rectangle…").

## Tools

| Tool | Args | What it does |
|---|---|---|
| `ocr_image` | `image_path` (req), `lang` (auto\|zh\|en, default auto) | Extract text from the image verbatim. |
| `describe_image` | `image_path` (req), `detail` (short\|medium\|long, default medium) | Describe the image objectively. |
| `answer_image` | `image_path` (req), `question` (req), `context` (opt) | Answer a question grounded in the image. |

Image file is read once, validated (magic-byte MIME check, 8 MiB cap), base64-encoded, and sent to Ark. **Never written to disk by the proxy.**

## Configuration

Project root `.env` (mode 600):

```ini
ARK_API_KEY=<your-doubao-ark-key>
ARK_BASE_URL=https://ark.cn-beijing.volces.com   (default)
ARK_MODEL=doubao-seed-2-0-mini-260215            (default)
```

`ARK_API_KEY`, `ARK_BASE_URL`, and `ARK_MODEL` can also be set via environment
variables, which take precedence over the file.

To get an `ARK_API_KEY`, sign up at <https://www.volcengine.com/> and create
an API key in the **方舟 (Ark)** console. The default model ID is
`doubao-seed-2-0-mini-260215`; replace it with whatever your account is
provisioned for (e.g. a Pro or Code variant).

## Tests

```bash
uv run python proxy/test_vision_proxy.py
```

Drives the proxy as a subprocess; asserts initialize, `tools/list`, and a
tool-call attempt with a fake key (which fails upstream with a 401, by
design — does not require a real API key).

## Requirements

- [`uv`](https://github.com/astral-sh/uv) — used to manage Python and run
  the proxy.
- Network access to `ark.cn-beijing.volses.com:443` from the machine
  running the proxy.
- An Ark API key from <https://www.volcengine.com/>.

## Transport

- **Stdin**: supports both **LSP/MCP-style `Content-Length` framing** and
  **line-delimited JSON** (auto-detected per message).
- **Stdout**: line-delimited JSON-RPC 2.0 responses (one JSON object per
  line).
- **Stderr**: human-readable logs only — never pollutes the JSON-RPC stream.

## Security

- API key lives in `./.env` with mode 600; never logged.
- `.env` is git-ignored; only `.env.example` is tracked.
- Image bytes are read once into memory and freed; never persisted, never
  echoed.
- Logs go to **stderr only**; stdout is reserved for JSON-RPC.

## License

MIT. See [LICENSE](LICENSE).

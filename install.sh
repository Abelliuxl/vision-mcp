#!/usr/bin/env bash
# Bootstrap .env in the project root (chmod 600) if missing, then show
# the MCP-client configuration snippet.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_ROOT/.env"
EXAMPLE_FILE="$REPO_ROOT/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        echo "ERROR: $EXAMPLE_FILE not found." >&2
        exit 1
    fi
    cp "$EXAMPLE_FILE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE (mode 600)."
    echo "Edit it and fill in ARK_API_KEY=<your-key>."
else
    echo "$ENV_FILE already exists; leaving it alone."
fi

cat <<EOF

Done. Configure your MCP client (Cursor / Trae / Claude Code) like:

  {
    "mcpServers": {
      "vision": {
        "command": "uv",
        "args": ["run", "--project", "$REPO_ROOT", "python", "$REPO_ROOT/proxy/vision_proxy.py"]
      }
    }
  }

EOF

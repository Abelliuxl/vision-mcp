#!/usr/bin/env bash
# Create the config directory with a placeholder .env file.
# Edit ~/.config/vision-mcp/.env and set ARK_API_KEY=<real-key>.

set -euo pipefail

CONFIG_DIR="$HOME/.config/vision-mcp"
ENV_FILE="$CONFIG_DIR/.env"

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
    cat > "$ENV_FILE" <<'EOF'
# Volcano Ark (Doubao). Set ARK_API_KEY to your real key.
ARK_API_KEY=
ARK_BASE_URL=https://ark.cn-beijing.volces.com
ARK_MODEL=doubao-seed-2-0-mini-260215
EOF
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE with placeholders."
    echo "Edit it and fill in ARK_API_KEY."
else
    echo "$ENV_FILE already exists; leaving it alone."
fi

echo
echo "Now configure your MCP client to launch:"
echo "  python3 $(pwd)/proxy/vision_proxy.py"
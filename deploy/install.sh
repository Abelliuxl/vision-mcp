#!/usr/bin/env bash
# Install vision-mcp on server94 (path scheme).
# Idempotent: subsequent runs only re-pull, re-sync, restart.

set -euo pipefail

REPO_DIR="/srv/vision-mcp"
ENV_FILE="/etc/vision-mcp/env.sh"
ENV_DIR="$(dirname "$ENV_FILE")"
NGINX_SNIPPET_SRC="$REPO_DIR/deploy/nginx.conf"
NGINX_TARGET="/etc/nginx/sites-enabled/main-page"
SUPERVISOR_SRC="$REPO_DIR/deploy/supervisord.conf"
SUPERVISOR_DST="/etc/supervisor/conf.d/vision-mcp.conf"
LOG_DIR="/var/log/vision-mcp"
NGINX_TMP="/var/lib/nginx/vision_tmp"

step() { echo; echo "==> $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

step "Pre-flight"
command -v python3 >/dev/null || fail "python3 missing"
command -v nginx >/dev/null || fail "nginx missing"
command -v supervisorctl >/dev/null || fail "supervisor missing"
command -v curl >/dev/null || fail "curl missing"
[[ "$(id -u)" -eq 0 ]] || fail "must run as root (sudo bash deploy/install.sh)"
[[ -f "$NGINX_TARGET" ]] || fail "$NGINX_TARGET not found; cannot inject location snippet"

step "Ensure uv is installed (bootstrap if missing)"
if ! command -v uv >/dev/null; then
    echo "uv not found; installing via official astral.sh installer."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV_BIN=""
    [[ -x /root/.local/bin/uv ]] && UV_BIN=/root/.local/bin/uv
    [[ -x /usr/local/bin/uv ]]   && UV_BIN=/usr/local/bin/uv
    if [[ -z "$UV_BIN" ]]; then
        echo "Official installer did not place uv on a default PATH; falling back to pip3."
        pip3 install --break-system-packages uv 2>/dev/null || pip3 install uv
        [[ -x /usr/local/bin/uv ]] && UV_BIN=/usr/local/bin/uv
    fi
    # Make uv globally visible: symlink to /usr/local/bin so it is on every user's PATH
    # (sudo's sanitized PATH won't include /root/.local/bin).
    if [[ -n "$UV_BIN" && ! -e /usr/local/bin/uv ]]; then
        ln -s "$UV_BIN" /usr/local/bin/uv
    fi
    # Belt-and-suspenders: add /root/.local/bin to PATH for the remainder of this script
    export PATH="/root/.local/bin:/usr/local/bin:$PATH"
    command -v uv >/dev/null || fail "uv still not found after install attempt"
fi
echo "uv: $(uv --version)"

step "Sync code into $REPO_DIR"
if [[ ! -d "$REPO_DIR/.git" ]]; then
    ORIGIN_URL="$(git -C "$REPO_DIR/.." remote get-url origin 2>/dev/null || true)"
    if [[ -z "$ORIGIN_URL" ]]; then
        ORIGIN_URL="https://github.com/Abelliuxl/vision-mcp.git"
    fi
    git clone "$ORIGIN_URL" "$REPO_DIR"
else
    git -C "$REPO_DIR" pull --ff-only
fi
chown -R ubuntu:ubuntu "$REPO_DIR"

step "Setup venv and install dependencies"
sudo -u ubuntu -H bash -lc "
    cd '$REPO_DIR'
    test -d .venv || uv venv
    source .venv/bin/activate
    uv pip install -e '.[dev]'
"

step "Ensure env file"
if [[ ! -f "$ENV_FILE" ]]; then
    ARK_API_KEY_VAL="${ARK_API_KEY:-}"
    if [[ -z "$ARK_API_KEY_VAL" ]]; then
        read -r -s -p "Volcano ARK_API_KEY: " ARK_API_KEY_VAL; echo
    fi
    [[ -n "$ARK_API_KEY_VAL" ]] || fail "ARK_API_KEY is required"
    ARK_BASE_URL_VAL="${ARK_BASE_URL:-https://ark.cn-beijing.volces.com}"
    ARK_MODEL_VAL="${ARK_MODEL:-doubao-seed-2-0-mini-260215}"
    VISION_BEARER_TOKEN_VAL="$(openssl rand -hex 32)"
    install -d -m 0750 -o root -g ubuntu "$ENV_DIR"
    cat > "$ENV_FILE" <<EOF
export ARK_BASE_URL="$ARK_BASE_URL_VAL"
export ARK_API_KEY="$ARK_API_KEY_VAL"
export ARK_MODEL="$ARK_MODEL_VAL"
export VISION_BEARER_TOKEN="$VISION_BEARER_TOKEN_VAL"
export HOST="127.0.0.1"
export PORT="8100"
EOF
    chmod 0640 "$ENV_FILE"
    chown root:ubuntu "$ENV_FILE"
    echo "Generated VISION_BEARER_TOKEN: $VISION_BEARER_TOKEN_VAL"
    echo "(Save this — your MCP client must send it as Bearer.)"
else
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

step "Install or update nginx location snippet in $NGINX_TARGET"
if grep -q "Begin vision-mcp injection" "$NGINX_TARGET"; then
    echo "Snippet already present; refreshing in place (token rotation, drift)."
    TMP="$(mktemp)"
    awk -v snippet="$NGINX_SNIPPET_SRC" -v token="$VISION_BEARER_TOKEN" '
        BEGIN {
            while ((getline line < snippet) > 0) snippet_buf = snippet_buf line "\n"
            close(snippet)
            gsub(/__FILL_TOKEN__/, token, snippet_buf)
        }
        /Begin vision-mcp injection/ { skip = 1; next }
        skip == 1 && /End vision-mcp injection/ { printf "%s", snippet_buf; skip = 0; next }
        skip == 0 { print }
    ' "$NGINX_TARGET" > "$TMP"
    install -m 0644 -o root -g root "$TMP" "$NGINX_TARGET"
    rm -f "$TMP"
else
    [[ -f "$NGINX_SNIPPET_SRC" ]] || fail "Snippet source not found: $NGINX_SNIPPET_SRC"
    install -d -m 0755 -o root -g root "$(dirname "$NGINX_TARGET")"
    cp "$NGINX_TARGET" "${NGINX_TARGET}.bak.$(date +%Y%m%d%H%M%S)"
    TMP="$(mktemp)"
    awk -v snippet="$NGINX_SNIPPET_SRC" -v token="$VISION_BEARER_TOKEN" '
        BEGIN {
            while ((getline line < snippet) > 0) snippet_buf = snippet_buf line "\n"
            close(snippet)
            gsub(/__FILL_TOKEN__/, token, snippet_buf)
        }
        /listen 80;/ && !done { printf "%s", snippet_buf; done = 1 }
        { print }
    ' "$NGINX_TARGET" > "$TMP"
    install -m 0644 -o root -g root "$TMP" "$NGINX_TARGET"
    rm -f "$TMP"
    echo "Injected snippet (backup: ${NGINX_TARGET}.bak.<timestamp>)."
fi

step "Ensure nginx body tmp dir"
install -d -m 0755 -o root -g www-data "$NGINX_TMP"

step "Install supervisor program"
install -d -m 0755 -o root -g root "$(dirname "$SUPERVISOR_DST")"
sed \
    -e "s|__ARK_BASE_URL__|$ARK_BASE_URL|g" \
    -e "s|__ARK_API_KEY__|$ARK_API_KEY|g" \
    -e "s|__ARK_MODEL__|$ARK_MODEL|g" \
    -e "s|__VISION_BEARER_TOKEN__|$VISION_BEARER_TOKEN|g" \
    "$SUPERVISOR_SRC" > "$SUPERVISOR_DST"
chmod 0644 "$SUPERVISOR_DST"

step "Ensure log dir"
install -d -m 0755 -o ubuntu -g ubuntu "$LOG_DIR"

step "Reload nginx"
nginx -t && systemctl reload nginx

step "Reload supervisor"
supervisorctl reread
supervisorctl update
supervisorctl restart vision-mcp 2>/dev/null || supervisorctl start vision-mcp

step "Smoke tests"
sleep 2
curl -sf https://liuxl.com.cn/healthz && echo
curl -s -o /dev/null -w "no-auth -> %{http_code}\n" -X POST \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    https://liuxl.com.cn/mcp
curl -s -o /dev/null -w "auth -> %{http_code}\n" -X POST \
    -H "Authorization: Bearer $VISION_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    https://liuxl.com.cn/mcp
echo
echo "Deployment complete."
echo "Bearer token (also see $ENV_FILE): $VISION_BEARER_TOKEN"
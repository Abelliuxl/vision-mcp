#!/usr/bin/env bash
# Install vision-mcp on server94.
# Idempotent: subsequent runs only re-pull, re-sync, restart.

set -euo pipefail

REPO_DIR="/srv/vision-mcp"
ENV_FILE="/etc/vision-mcp/env.sh"
ENV_DIR="$(dirname "$ENV_FILE")"
NGINX_SITE_SRC="$REPO_DIR/deploy/nginx.conf"
NGINX_SITE_DST="/etc/nginx/sites-available/vision-mcp"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/vision-mcp"
SUPERVISOR_SRC="$REPO_DIR/deploy/supervisord.conf"
SUPERVISOR_DST="/etc/supervisor/conf.d/vision-mcp.conf"
LOG_DIR="/var/log/vision-mcp"
NGINX_TMP="/var/lib/nginx/vision_tmp"

step() { echo; echo "==> $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

step "Pre-flight"
command -v python3 >/dev/null || fail "python3 missing"
command -v uv >/dev/null || fail "uv missing (apt install uv / pip install uv / brew install uv)"
command -v nginx >/dev/null || fail "nginx missing"
command -v certbot >/dev/null || fail "certbot missing"
command -v supervisorctl >/dev/null || fail "supervisor missing"
[[ "$(id -u)" -eq 0 ]] || fail "must run as root (sudo bash deploy/install.sh)"

step "Sync code into $REPO_DIR"
if [[ ! -d "$REPO_DIR/.git" ]]; then
    git clone "$(git -C "$(dirname "$0")" remote get-url origin)" "$REPO_DIR"
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
    echo "(Save this; it is the Bearer token your MCP client must send.)"
else
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

step "Install nginx site"
install -d -m 0755 -o root -g root "$(dirname "$NGINX_SITE_DST")"
sed "s|Bearer __FILL_TOKEN__|Bearer $VISION_BEARER_TOKEN|" "$NGINX_SITE_SRC" \
    > "$NGINX_SITE_DST"
chmod 0644 "$NGINX_SITE_DST"
ln -sfn "$NGINX_SITE_DST" "$NGINX_SITE_LINK"

step "Ensure nginx body tmp dir"
install -d -m 0755 -o root -g www-data "$NGINX_TMP"

step "Install supervisor program"
sed \
    -e "s|__ARK_BASE_URL__|$ARK_BASE_URL|g" \
    -e "s|__ARK_API_KEY__|$ARK_API_KEY|g" \
    -e "s|__ARK_MODEL__|$ARK_MODEL|g" \
    -e "s|__VISION_BEARER_TOKEN__|$VISION_BEARER_TOKEN|g" \
    "$SUPERVISOR_SRC" > "$SUPERVISOR_DST"

step "Ensure log dir"
install -d -m 0755 -o ubuntu -g ubuntu "$LOG_DIR"

step "Reissue cert (idempotent; covers vision SAN)"
certbot --nginx -d liuxl.com.cn -d www.liuxl.com.cn -d vision.liuxl.com.cn \
    --cert-name liuxl.com.cn --expand --no-eff-email --agree-tos -m liuxl@liuxl.com.cn \
    || true

step "Reload nginx"
nginx -t && systemctl reload nginx

step "Reload supervisor"
supervisorctl reread
supervisorctl update
supervisorctl restart vision-mcp || supervisorctl start vision-mcp

step "Smoke tests"
sleep 2
curl -sf https://vision.liuxl.com.cn/healthz && echo
curl -s -o /dev/null -w "no-auth → %{http_code}\n" -X POST \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    https://vision.liuxl.com.cn/mcp
curl -s -o /dev/null -w "auth → %{http_code}\n" -X POST \
    -H "Authorization: Bearer $VISION_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    https://vision.liuxl.com.cn/mcp
echo
echo "Deployment complete."
echo "Bearer token (also see $ENV_FILE): $VISION_BEARER_TOKEN"
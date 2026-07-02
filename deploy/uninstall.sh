#!/usr/bin/env bash
# Removes the vision-mcp deployment.
# Removes: supervisor program, nginx location snippet, env file, /srv/vision-mcp.
# Re-runnable: the uninstall is idempotent.

set -euo pipefail

NGINX_TARGET="/etc/nginx/sites-enabled/main-page"
START="# Begin vision-mcp injection"
END="# End vision-mcp injection"

step() { echo "==> $*"; }

step "Stop and remove supervisor program"
supervisorctl stop vision-mcp 2>/dev/null || true
rm -f /etc/supervisor/conf.d/vision-mcp.conf
supervisorctl reread
supervisorctl update

step "Remove vision-mcp location from $NGINX_TARGET"
if [[ -f "$NGINX_TARGET" ]] && grep -q "$START" "$NGINX_TARGET"; then
    cp "$NGINX_TARGET" "${NGINX_TARGET}.uninst.$(date +%Y%m%d%H%M%S)"
    TMP="$(mktemp)"
    awk -v start="$START" -v end="$END" '
        $0 ~ start { skip = 1; next }
        skip == 1 && $0 ~ end { skip = 0; next }
        skip == 0 { print }
    ' "$NGINX_TARGET" > "$TMP"
    install -m 0644 -o root -g root "$TMP" "$NGINX_TARGET"
    rm -f "$TMP"
    nginx -t && systemctl reload nginx
    echo "Snippet removed."
else
    echo "No snippet present in $NGINX_TARGET; skipping."
fi

step "Purge code and secrets"
rm -rf /srv/vision-mcp /etc/vision-mcp /var/log/vision-mcp
echo "Purged /srv/vision-mcp, /etc/vision-mcp, /var/log/vision-mcp."
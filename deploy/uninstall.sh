#!/usr/bin/env bash
# Removes the vision-mcp deployment. Leaves the git clone in place unless --purge is given.

set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

step() { echo "==> $*"; }

step "Disable supervisor program"
supervisorctl stop vision-mcp 2>/dev/null || true
rm -f /etc/supervisor/conf.d/vision-mcp.conf
supervisorctl reread
supervisorctl update

step "Remove nginx site"
rm -f /etc/nginx/sites-enabled/vision-mcp
rm -f /etc/nginx/sites-available/vision-mcp
nginx -t && systemctl reload nginx

if [[ "$PURGE" -eq 1 ]]; then
    step "Purge code and secrets"
    rm -rf /srv/vision-mcp /etc/vision-mcp /var/log/vision-mcp
    echo "Purged /srv/vision-mcp, /etc/vision-mcp, /var/log/vision-mcp."
else
    step "Kept code in /srv/vision-mcp and secrets in /etc/vision-mcp (use --purge to remove)."
fi
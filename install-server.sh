#!/usr/bin/env bash
set -euo pipefail

APP_NAME="kodi-xbox-proxy"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/$APP_NAME.service"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

cd "$APP_DIR"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools
"$VENV_DIR/bin/python" -m pip install -e "$APP_DIR"

mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Kodi Xbox Proxy Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/kodi-xbox-proxy
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kodi-xbox-proxy

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$APP_NAME.service"

echo "Installed and started $APP_NAME"
echo "Status:  systemctl --user status $APP_NAME"
echo "Logs:    journalctl --user -u $APP_NAME -f"
echo "UI:      http://localhost:8080/"
echo "WS:      ws://$(hostname -I | awk '{print $1}'):9191"

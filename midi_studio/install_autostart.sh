#!/bin/bash
# Installa MIDI Studio come servizio di macOS: parte da solo a ogni accesso e
# viene riavviato se si chiude in modo anomalo. Dopo l'installazione ti basta
# aprire http://localhost:5080 — nessun terminale da aprire.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.alessandrolocurcio.midistudio"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$(command -v python3)"
mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$DIR/midi_studio.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$DIR/logs/midistudio.out.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/logs/midistudio.err.log</string>
</dict>
</plist>
PLISTEOF

# Se c'è un'istanza avviata a mano, la fermo: altrimenti il servizio non prende
# la porta 5080 e resta inattivo.
PID_MANUALE="$(lsof -nP -iTCP:5080 -sTCP:LISTEN -t 2>/dev/null || true)"
if [ -n "$PID_MANUALE" ]; then
    echo "* Fermo l'istanza manuale (PID $PID_MANUALE)…"
    kill "$PID_MANUALE" 2>/dev/null || true
    sleep 2
fi

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 4

echo "--- servizio ---"
launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state = |pid = " | head -3 || true
if lsof -nP -iTCP:5080 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✅ MIDI Studio attivo: http://localhost:5080 — partirà da solo a ogni accesso."
else
    echo "⚠️  Installato, ma la porta 5080 non risponde: vedi $DIR/logs/midistudio.err.log"
fi

#!/bin/bash
# Rimuove l'avvio automatico di MIDI Studio (ferma il servizio e cancella il plist).
set -euo pipefail
LABEL="com.alessandrolocurcio.midistudio"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "🗑️  Autostart rimosso: MIDI Studio non partirà più da solo."
echo "   Per avviarlo a mano: python3 midi_studio.py"

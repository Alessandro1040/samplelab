#!/bin/bash
# Gestione rapida di MIDI Studio (per non dover ricordare i comandi launchctl).
#   ./gestisci.sh status    → stato del servizio
#   ./gestisci.sh stop      → ferma ora (riparte al prossimo accesso)
#   ./gestisci.sh start     → avvia ora
#   ./gestisci.sh restart   → riavvia ora
#   ./gestisci.sh log       → ultime righe di log
LABEL="com.alessandrolocurcio.midistudio"
UID_N="$(id -u)"
DIR="$(cd "$(dirname "$0")" && pwd)"

case "${1:-status}" in
  start)   launchctl kickstart "gui/$UID_N/$LABEL" && echo "✅ avviato — http://localhost:5080" ;;
  stop)    launchctl kill SIGTERM "gui/$UID_N/$LABEL" && echo "⏹️  fermato (riparte al prossimo accesso)" ;;
  restart) launchctl kickstart -k "gui/$UID_N/$LABEL" && echo "🔄 riavviato — http://localhost:5080" ;;
  status)  launchctl print "gui/$UID_N/$LABEL" 2>/dev/null | grep -E "state = |pid = |path = " | head -4 \
             || echo "servizio non installato (lancia ./install_autostart.sh)" ;;
  log)     tail -n 30 "$DIR/logs/midistudio.out.log" 2>/dev/null; tail -n 20 "$DIR/logs/midistudio.err.log" 2>/dev/null ;;
  *)       echo "uso: $0 {status|start|stop|restart|log}" ;;
esac

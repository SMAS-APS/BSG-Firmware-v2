#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/bsg-gateway"
CONFIG_DIR="/etc/bsg-gateway"
CONFIG_FILE="$CONFIG_DIR/config.json"
SERVICE_FILE="/etc/systemd/system/bsg-gateway.service"
SERVICE_NAME="bsg-gateway.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AMMS_SOURCE="$SCRIPT_DIR/../external/AMMSUtils/amms"

AMMS_TOKEN="${AMMS_TOKEN:-}"
AMMS_URL="${AMMS_URL:-https://weather.iacca.ml/api/data/point}"
START_SERVICE=1

usage() {
    cat <<'EOF'
Uso: sudo bash install.sh [opzioni]

Opzioni:
  --token TOKEN   token AMMS; se omesso viene richiesto senza mostrarlo
  --url URL       URL HTTPS AMMS
  --no-start      installa e abilita il servizio senza avviarlo subito
  -h, --help      mostra questo aiuto
EOF
}

while (($#)); do
    case "$1" in
        --token)
            [[ $# -ge 2 ]] || { echo "Manca il valore di --token" >&2; exit 2; }
            AMMS_TOKEN="$2"
            shift 2
            ;;
        --url)
            [[ $# -ge 2 ]] || { echo "Manca il valore di --url" >&2; exit 2; }
            AMMS_URL="$2"
            shift 2
            ;;
        --no-start)
            START_SERVICE=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Opzione sconosciuta: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ((EUID != 0)); then
    echo "Eseguire questo installer con: sudo bash install.sh" >&2
    exit 1
fi

for source_file in gateway.py bresser_native.py config.example.json bsg-gateway.service README.md; do
    [[ -f "$SCRIPT_DIR/$source_file" ]] || {
        echo "File mancante: $SCRIPT_DIR/$source_file" >&2
        exit 1
    }
done

if [[ ! -f "$AMMS_SOURCE/__init__.py" ]]; then
    echo "Submodule AMMSUtils mancante." >&2
    echo "Dalla radice del repository eseguire: git submodule update --init --recursive" >&2
    exit 1
fi

if [[ ! -f "$CONFIG_FILE" && -z "$AMMS_TOKEN" ]]; then
    if [[ -t 0 ]]; then
        read -r -s -p "Token AMMS: " AMMS_TOKEN
        echo
    else
        echo "Prima installazione: specificare --token oppure AMMS_TOKEN." >&2
        exit 2
    fi
fi

[[ "$AMMS_URL" == https://* ]] || {
    echo "L'URL AMMS deve iniziare con https://" >&2
    exit 2
}

echo "[1/6] Installazione dipendenze di sistema"
apt-get update
packages=(python3 python3-spidev python3-gpiozero ca-certificates)
if apt-cache show python3-lgpio >/dev/null 2>&1; then
    packages+=(python3-lgpio)
else
    packages+=(python3-rpi.gpio)
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"

echo "[2/6] Abilitazione interfaccia SPI"
raspi-config nonint do_spi 0
modprobe spi_bcm2835 || true

echo "[3/6] Creazione utente di servizio"
getent group spi >/dev/null || groupadd --system spi
getent group gpio >/dev/null || groupadd --system gpio
if ! id -u bsg-gateway >/dev/null 2>&1; then
    useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin bsg-gateway
fi
usermod -a -G spi,gpio bsg-gateway

echo "[4/6] Installazione applicazione e configurazione"
install -d -o root -g bsg-gateway -m 0750 "$INSTALL_DIR" "$CONFIG_DIR"
install -o root -g bsg-gateway -m 0644 \
    "$SCRIPT_DIR/gateway.py" \
    "$SCRIPT_DIR/bresser_native.py" \
    "$SCRIPT_DIR/README.md" \
    "$INSTALL_DIR/"
install -d -o root -g bsg-gateway -m 0755 \
    "$INSTALL_DIR/amms" "$INSTALL_DIR/amms/transports"
install -o root -g bsg-gateway -m 0644 \
    "$AMMS_SOURCE/__init__.py" \
    "$AMMS_SOURCE/client.py" \
    "$AMMS_SOURCE/payload.py" \
    "$INSTALL_DIR/amms/"
install -o root -g bsg-gateway -m 0644 \
    "$AMMS_SOURCE/transports/__init__.py" \
    "$AMMS_SOURCE/transports/cpython_http.py" \
    "$INSTALL_DIR/amms/transports/"

if [[ ! -f "$CONFIG_FILE" ]]; then
    install -o root -g bsg-gateway -m 0640 \
        "$SCRIPT_DIR/config.example.json" "$CONFIG_FILE"
fi

if [[ -n "$AMMS_TOKEN" ]]; then
    python3 - "$CONFIG_FILE" "$AMMS_TOKEN" "$AMMS_URL" <<'PY'
import json
import os
import sys
import tempfile

path, token, url = sys.argv[1:]
with open(path, "r", encoding="utf-8") as stream:
    config = json.load(stream)
config.setdefault("amms", {})["token"] = token
config["amms"]["url"] = url
directory = os.path.dirname(path)
descriptor, temporary = tempfile.mkstemp(dir=directory, prefix="config.", text=True)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
fi
chown root:bsg-gateway "$CONFIG_FILE"
chmod 0640 "$CONFIG_FILE"

python3 - "$CONFIG_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    config = json.load(stream)
if not config.get("amms", {}).get("token", "").strip():
    raise SystemExit("Token AMMS mancante nella configurazione")
if not config.get("amms", {}).get("url", "").startswith("https://"):
    raise SystemExit("URL AMMS non valido")
PY

echo "[5/6] Installazione servizio con riavvio automatico"
install -o root -g root -m 0644 "$SCRIPT_DIR/bsg-gateway.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "[6/6] Controllo finale"
PYTHONPATH="$INSTALL_DIR" python3 -c "import amms, bresser_native; print('AMMSUtils e decoder importati correttamente')"

if ((START_SERVICE == 1)); then
    if [[ -e /dev/spidev0.0 ]]; then
        systemctl restart "$SERVICE_NAME"
        echo "Servizio avviato. Log: journalctl -u $SERVICE_NAME -f"
    else
        systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        echo "SPI abilitato, ma /dev/spidev0.0 non è ancora disponibile."
        echo "Riavviare il Raspberry Pi: il servizio partirà automaticamente al boot."
    fi
else
    echo "Servizio installato e abilitato; avvio immediato omesso."
fi

echo "Configurazione: $CONFIG_FILE"

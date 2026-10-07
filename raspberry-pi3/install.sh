#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/bsg-gateway"
CONFIG_DIR="/etc/bsg-gateway"
CONFIG_FILE="$CONFIG_DIR/config.json"
ENROLLMENT_FILE="$CONFIG_DIR/enrollment.json"
SERVICE_FILE="/etc/systemd/system/bsg-gateway.service"
SERVICE_NAME="bsg-gateway.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AMMS_SOURCE="$SCRIPT_DIR/../external/AMMSUtils/amms"

AMMS_TOKEN="${AMMS_TOKEN:-}"
AMMS_URL_EXPLICIT=0
if [[ -n "${AMMS_URL:-}" ]]; then
    AMMS_URL_EXPLICIT=1
fi
AMMS_URL="${AMMS_URL:-https://weather.iacca.ml/api/data/point}"
AMMS_ENROLL_URL="${AMMS_ENROLL_URL:-}"
AMMS_ENROLL_CODE="${AMMS_ENROLL_CODE:-}"
AMMS_TRANSPORT="${AMMS_TRANSPORT:-}"
AMMS_MQTT_HOST="${AMMS_MQTT_HOST:-}"
AMMS_MQTT_PORT="${AMMS_MQTT_PORT:-8883}"
AMMS_MQTT_CA_URL="${AMMS_MQTT_CA_URL:-}"
ROTATE_KEY=0
START_SERVICE=1

usage() {
    cat <<'EOF'
Uso: sudo bash install.sh [opzioni]

Opzioni:
  --token TOKEN       usa il token Bearer legacy invece di HMAC
  --url URL           URL HTTPS per l'invio dei dati
  --enroll-url URL    registra automaticamente la chiave tramite HTTPS
  --mqtt-host HOST    usa MQTT/TLS e pubblica verso questo broker
  --mqtt-port PORT    porta MQTT/TLS (predefinita: 8883)
  --mqtt-ca-url URL   URL HTTPS del certificato CA MQTT
  --http              mantiene il trasporto HTTPS tradizionale
  --rotate-key        genera una nuova chiave mantenendo l'ID stazione
  --no-start          installa e abilita il servizio senza avviarlo subito
  -h, --help          mostra questo aiuto

Il codice monouso per --enroll-url viene letto da AMMS_ENROLL_CODE oppure
richiesto senza mostrarlo sullo schermo.
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
            AMMS_URL_EXPLICIT=1
            shift 2
            ;;
        --enroll-url)
            [[ $# -ge 2 ]] || { echo "Manca il valore di --enroll-url" >&2; exit 2; }
            AMMS_ENROLL_URL="$2"
            shift 2
            ;;
        --rotate-key)
            ROTATE_KEY=1
            shift
            ;;
        --mqtt-host)
            [[ $# -ge 2 ]] || { echo "Manca il valore di --mqtt-host" >&2; exit 2; }
            AMMS_MQTT_HOST="$2"
            AMMS_TRANSPORT="mqtt"
            shift 2
            ;;
        --mqtt-port)
            [[ $# -ge 2 ]] || { echo "Manca il valore di --mqtt-port" >&2; exit 2; }
            AMMS_MQTT_PORT="$2"
            shift 2
            ;;
        --mqtt-ca-url)
            [[ $# -ge 2 ]] || { echo "Manca il valore di --mqtt-ca-url" >&2; exit 2; }
            AMMS_MQTT_CA_URL="$2"
            shift 2
            ;;
        --http)
            AMMS_TRANSPORT="http"
            shift
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

for source_file in gateway.py bresser_native.py mqtt_transport.py config.example.json bsg-gateway.service README.md; do
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

[[ "$AMMS_URL" == https://* ]] || {
    echo "L'URL AMMS deve iniziare con https://" >&2
    exit 2
}
if [[ -n "$AMMS_ENROLL_URL" && "$AMMS_ENROLL_URL" != https://* ]]; then
    echo "L'URL di registrazione deve iniziare con https://" >&2
    exit 2
fi
if [[ -n "$AMMS_MQTT_CA_URL" && "$AMMS_MQTT_CA_URL" != https://* ]]; then
    echo "L'URL della CA MQTT deve iniziare con https://" >&2
    exit 2
fi
[[ "$AMMS_MQTT_PORT" =~ ^[0-9]+$ ]] || {
    echo "La porta MQTT deve essere numerica" >&2
    exit 2
}

echo "[1/6] Installazione dipendenze di sistema"
apt-get update
packages=(python3 python3-spidev python3-gpiozero python3-paho-mqtt ca-certificates)
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
    "$SCRIPT_DIR/mqtt_transport.py" \
    "$SCRIPT_DIR/README.md" \
    "$INSTALL_DIR/"
install -d -o root -g bsg-gateway -m 0755 \
    "$INSTALL_DIR/amms" "$INSTALL_DIR/amms/transports"
install -o root -g bsg-gateway -m 0644 \
    "$AMMS_SOURCE/__init__.py" \
    "$AMMS_SOURCE/auth.py" \
    "$AMMS_SOURCE/client.py" \
    "$AMMS_SOURCE/credentials.py" \
    "$AMMS_SOURCE/payload.py" \
    "$AMMS_SOURCE/mqtt.py" \
    "$INSTALL_DIR/amms/"
install -o root -g bsg-gateway -m 0644 \
    "$AMMS_SOURCE/transports/__init__.py" \
    "$AMMS_SOURCE/transports/cpython_http.py" \
    "$INSTALL_DIR/amms/transports/"

CONFIG_CREATED=0
if [[ ! -f "$CONFIG_FILE" ]]; then
    install -o root -g bsg-gateway -m 0640 \
        "$SCRIPT_DIR/config.example.json" "$CONFIG_FILE"
    CONFIG_CREATED=1
fi

PYTHONPATH="$INSTALL_DIR" python3 - \
    "$CONFIG_FILE" "$ENROLLMENT_FILE" "$AMMS_TOKEN" "$AMMS_URL" \
    "$AMMS_URL_EXPLICIT" "$CONFIG_CREATED" "$ROTATE_KEY" \
    "$AMMS_TRANSPORT" "$AMMS_MQTT_HOST" "$AMMS_MQTT_PORT" <<'PY'
import json
import os
import sys
import tempfile
import urllib.parse

from amms import generate_credentials


def atomic_json(path, value, mode):
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix="config.", text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


path, enrollment_path, token, url = sys.argv[1:5]
url_explicit, config_created, rotate_key = (value == "1" for value in sys.argv[5:8])
transport, mqtt_host, mqtt_port = sys.argv[8:11]
with open(path, "r", encoding="utf-8") as stream:
    config = json.load(stream)
amms = config.setdefault("amms", {})
if config_created or url_explicit or not amms.get("url"):
    amms["url"] = url
if transport:
    amms["transport"] = transport
elif not config_created and "transport" not in amms:
    # Un aggiornamento non cambia automaticamente il trasporto di una stazione attiva.
    amms["transport"] = "http"
if amms.get("transport") == "mqtt":
    derived_host = urllib.parse.urlsplit(amms["url"]).hostname
    current_host = "" if config_created and url_explicit else amms.get("mqtt_host")
    amms["mqtt_host"] = mqtt_host or current_host or derived_host
    amms["mqtt_port"] = int(mqtt_port)
    amms.setdefault("mqtt_ca_cert", "/etc/bsg-gateway/mqtt-ca.crt")

generated = None
if token:
    amms.update({
        "auth_mode": "bearer",
        "token": token,
        "station_id": "",
        "key_id": "",
        "secret_hex": "",
    })
    amms["transport"] = "http"
    if os.path.exists(enrollment_path):
        os.unlink(enrollment_path)
else:
    hmac_complete = all(
        amms.get(name) and str(amms.get(name)).strip()
        for name in ("station_id", "key_id", "secret_hex")
    )
    legacy_bearer = (
        amms.get("auth_mode", "") in ("", "bearer")
        and amms.get("token")
        and str(amms.get("token")).strip()
    )
    if rotate_key or (not hmac_complete and not legacy_bearer):
        generated = generate_credentials(amms.get("station_id") or None)
        amms.update(generated)
        amms["auth_mode"] = "hmac-sha256"
        amms["token"] = ""
    elif hmac_complete:
        amms["auth_mode"] = "hmac-sha256"
    else:
        amms["auth_mode"] = "bearer"

atomic_json(path, config, 0o640)
if generated is not None:
    atomic_json(enrollment_path, generated, 0o600)
PY

chown root:bsg-gateway "$CONFIG_FILE"
chmod 0640 "$CONFIG_FILE"
if [[ -f "$ENROLLMENT_FILE" ]]; then
    chown root:root "$ENROLLMENT_FILE"
    chmod 0600 "$ENROLLMENT_FILE"
fi

PYTHONPATH="$INSTALL_DIR" python3 - "$CONFIG_FILE" "$AMMS_MQTT_CA_URL" <<'PY'
import json
import os
import ssl
import sys
import tempfile
import urllib.parse
import urllib.request

config_path, explicit_url = sys.argv[1:]
with open(config_path, "r", encoding="utf-8") as stream:
    amms = json.load(stream).get("amms", {})
if amms.get("transport") != "mqtt":
    raise SystemExit(0)

ca_path = amms.get("mqtt_ca_cert", "/etc/bsg-gateway/mqtt-ca.crt")
api = urllib.parse.urlsplit(amms["url"])
ca_url = explicit_url or urllib.parse.urlunsplit((api.scheme, api.netloc, "/api/mqtt/ca.crt", "", ""))
with urllib.request.urlopen(ca_url, timeout=20, context=ssl.create_default_context()) as response:
    pem = response.read()
if b"-----BEGIN CERTIFICATE-----" not in pem:
    raise SystemExit("Il server non ha restituito una CA MQTT valida")

descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(ca_path), prefix="mqtt-ca.")
try:
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(pem)
    os.chmod(temporary, 0o644)
    os.replace(temporary, ca_path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print("CA MQTT installata da " + ca_url)
PY

PYTHONPATH="$INSTALL_DIR" python3 - "$CONFIG_FILE" <<'PY'
import json
import sys

from amms import HMACAuth

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    config = json.load(stream)
amms = config.get("amms", {})
if not amms.get("url", "").startswith("https://"):
    raise SystemExit("URL AMMS non valido")
if amms.get("auth_mode") == "hmac-sha256":
    HMACAuth.from_config(amms)
elif amms.get("auth_mode") == "bearer" and amms.get("token", "").strip():
    pass
else:
    raise SystemExit("Credenziali AMMS mancanti o non valide")
PY

ENROLLMENT_PENDING=0
if [[ -f "$ENROLLMENT_FILE" ]]; then
    if [[ -n "$AMMS_ENROLL_URL" ]]; then
        if [[ -z "$AMMS_ENROLL_CODE" ]]; then
            if [[ -t 0 ]]; then
                read -r -s -p "Codice monouso di registrazione: " AMMS_ENROLL_CODE
                echo
            else
                echo "Impostare AMMS_ENROLL_CODE per la registrazione non interattiva." >&2
                exit 2
            fi
        fi
        python3 - "$ENROLLMENT_FILE" "$AMMS_ENROLL_URL" "$AMMS_ENROLL_CODE" <<'PY'
import json
import os
import ssl
import sys
import urllib.request

path, url, code = sys.argv[1:]
with open(path, "rb") as stream:
    body = stream.read()
request = urllib.request.Request(
    url,
    data=body,
    headers={
        "Authorization": "Bearer " + code,
        "Content-Type": "application/json",
        "User-Agent": "BSG-Installer/2.1",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
    if not 200 <= response.status < 300:
        raise SystemExit("Registrazione AMMS rifiutata: HTTP %d" % response.status)
os.unlink(path)
PY
        AMMS_ENROLL_CODE=""
        echo "Credenziali HMAC registrate sul server."
    else
        ENROLLMENT_PENDING=1
    fi
fi

echo "[5/6] Installazione servizio con riavvio automatico"
install -o root -g root -m 0644 "$SCRIPT_DIR/bsg-gateway.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "[6/6] Controllo finale"
PYTHONPATH="$INSTALL_DIR" python3 -c "import amms, bresser_native, mqtt_transport; print('AMMSUtils, MQTT e decoder importati correttamente')"

if ((ENROLLMENT_PENDING == 1)); then
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    echo "Credenziali generate, ma la stazione non e' ancora registrata sul server."
    echo "Pacchetto protetto da importare sul server: $ENROLLMENT_FILE"
    echo "Dopo la registrazione avviare: systemctl start $SERVICE_NAME"
elif ((START_SERVICE == 1)); then
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

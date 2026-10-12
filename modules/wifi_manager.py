import socket
import time
import json
import select

import network

from config_store import save, validate_weather_underground, validate_amms, replace_file
from wu_support import canonical_sensor_values
from bsg_runtime import FIRMWARE_VERSION, FIRMWARE_STAGE
from bresser_protocols import AutoReceiver
from rx_led import ReceiveLED
from ap_uplink import Uplink


def _interface_id(name, fallback):
    wlan_class_value = getattr(network.WLAN, name, None)
    if wlan_class_value is not None:
        return wlan_class_value
    return getattr(network, name.replace("IF_", "") + "_IF", fallback)


STA_IF = _interface_id("IF_STA", 0)
AP_IF = _interface_id("IF_AP", 1)


def station():
    return network.WLAN(STA_IF)


def connect(ssid, password, timeout_seconds=20):
    wlan = station()
    wlan.active(True)
    if wlan.isconnected():
        return wlan

    print("Connessione Wi-Fi a", ssid)
    wlan.connect(ssid, password)
    deadline = time.ticks_add(time.ticks_ms(), timeout_seconds * 1000)
    while not wlan.isconnected():
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            try:
                wlan.disconnect()
            except OSError:
                pass
            raise OSError("Timeout connessione Wi-Fi")
        time.sleep_ms(250)

    print("Wi-Fi connesso:", wlan.ifconfig())
    return wlan


def ensure_connected(config, timeout_seconds=20):
    wlan = station()
    if wlan.isconnected():
        return wlan
    return connect(
        config["wifi"].get("ssid", ""),
        config["wifi"].get("password", ""),
        timeout_seconds,
    )


def _url_decode(value):
    result = bytearray()
    index = 0
    while index < len(value):
        char = value[index]
        if char == 43:
            result.append(32)
            index += 1
        elif char == 37 and index + 2 < len(value):
            result.append(int(value[index + 1:index + 3], 16))
            index += 3
        else:
            result.append(char)
            index += 1
    return result.decode("utf-8")


def _parse_form(body):
    fields = {}
    for item in body.split(b"&"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        fields[_url_decode(key)] = _url_decode(value)
    return fields


def _send_response(client, status, body):
    encoded = body.encode("utf-8")
    header = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n\r\n"
    ) % (status, len(encoded))
    client.write(header.encode("utf-8"))
    client.write(encoded)


def _page(message=""):
    return """<!doctype html>
<html lang=\"it\"><head><meta name=\"viewport\" content=\"width=device-width\">
<title>Bresser Gateway</title>
<style>body{font-family:sans-serif;max-width:34rem;margin:2rem auto;padding:0 1rem}
label{display:block;margin-top:1rem}input,select,textarea{width:100%;box-sizing:border-box;padding:.65rem}
button{margin-top:1.4rem;padding:.7rem 1rem}.message{color:#075}</style></head>
<body><h1>Bresser Gateway</h1><p>Configura rete, AMMS e Weather Underground.</p>
<p class=\"message\">%s</p>
<form method=\"post\" action=\"/save\">
<label>Nome rete Wi-Fi<input name=\"ssid\" required></label>
<label>Password Wi-Fi<input name=\"password\" type=\"password\"></label>
<label>Trasporto<select name=\"transport\">
<option value=\"mqtt\">MQTT/TLS (consigliato)</option><option value=\"http\">HTTPS</option>
</select></label>
<label>Modalita' autenticazione<select name=\"auth_mode\">
<option value=\"hmac-sha256\">HMAC-SHA256</option><option value=\"bearer\">Bearer legacy</option>
</select></label>
<label>ID stazione<input name=\"station_id\"></label>
<label>ID chiave<input name=\"key_id\"></label>
<label>Chiave HMAC esadecimale<input name=\"secret_hex\" type=\"password\"></label>
<label>Token AMMS precedente<input name=\"token\" type=\"password\"></label>
<label>URL API<input name=\"url\" value=\"https://weather.iacca.ml/api/data/point\" required></label>
<label>Server MQTT<input name=\"mqtt_host\" value=\"weather.iacca.ml\"></label>
<label>Porta MQTT/TLS<input name=\"mqtt_port\" value=\"8883\" inputmode=\"numeric\"></label>
<label>Certificato CA MQTT (PEM)<textarea name=\"mqtt_ca_pem\" rows=\"7\" placeholder=\"-----BEGIN CERTIFICATE-----\"></textarea></label>
<h2>Weather Underground</h2>
<label><input name=\"wu_enabled\" type=\"checkbox\" style=\"width:auto\"> Abilita upload WU</label>
<label>ID stazione WU<input name=\"wu_station_id\"></label>
<label>Station key WU<input name=\"wu_station_key\" type=\"password\"></label>
<label>Modalita' WU<select name=\"wu_mode\">
<option value=\"rapidfire\">RapidFire</option><option value=\"standard\">Invio standard PWS</option>
</select></label>
<label>Intervallo upload WU (secondi)<input name=\"wu_interval\" value=\"10\" inputmode=\"numeric\"></label>
<label>Offset UTC locale (minuti)<input name=\"wu_utc_offset\" value=\"60\" inputmode=\"numeric\"></label>
<button type=\"submit\">Salva e riavvia</button></form></body></html>""" % message


def _save_mqtt_ca(path, pem):
    if "-----BEGIN CERTIFICATE-----" not in pem:
        raise ValueError("certificato CA MQTT non valido")
    temporary_path = path + ".tmp"
    with open(temporary_path, "w") as stream:
        stream.write(pem)
        if not pem.endswith("\n"):
            stream.write("\n")
    replace_file(temporary_path, path)


def _file_exists(path):
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def provision(config, ap_name="Bresser Gateway"):
    access_point = network.WLAN(AP_IF)
    access_point.active(True)
    access_point.config(ssid=ap_name, security=0)
    print("Configurazione disponibile su http://192.168.4.1")

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 80))
    server.listen(1)

    try:
        while True:
            client, _ = server.accept()
            try:
                request_line = client.readline()
                if not request_line:
                    continue

                headers = {}
                while True:
                    line = client.readline()
                    if not line or line == b"\r\n":
                        break
                    name, value = line.split(b":", 1)
                    headers[name.decode().lower()] = value.strip().decode()

                method, path, _ = request_line.split(None, 2)
                if method == b"POST" and path == b"/save":
                    length = int(headers.get("content-length", "0"))
                    form = _parse_form(client.read(length))
                    config["wifi"]["ssid"] = form.get("ssid", "")
                    config["wifi"]["password"] = form.get("password", "")
                    config["amms"]["transport"] = form.get("transport", "mqtt")
                    config["amms"]["auth_mode"] = form.get("auth_mode", "hmac-sha256")
                    config["amms"]["station_id"] = form.get("station_id", "")
                    config["amms"]["key_id"] = form.get("key_id", "")
                    config["amms"]["secret_hex"] = form.get("secret_hex", "")
                    config["amms"]["token"] = form.get("token", "")
                    config["amms"]["url"] = form.get("url", config["amms"]["url"])
                    config["amms"]["mqtt_host"] = form.get("mqtt_host", "")
                    config["amms"]["mqtt_port"] = int(form.get("mqtt_port", "8883"))
                    config["amms"]["mqtt_ca_cert"] = "/mqtt-ca.crt"
                    wu = config["weather_underground"]
                    wu["enabled"] = form.get("wu_enabled") == "on"
                    wu["station_id"] = form.get("wu_station_id", "")
                    wu["station_key"] = form.get("wu_station_key", "")
                    wu["mode"] = form.get("wu_mode", "rapidfire")
                    wu["upload_interval_seconds"] = int(form.get("wu_interval", "10"))
                    wu["utc_offset_minutes"] = int(form.get("wu_utc_offset", "60"))
                    validate_weather_underground(config)
                    mqtt_ca_pem = form.get("mqtt_ca_pem", "").strip()
                    if config["amms"]["transport"] == "mqtt" and mqtt_ca_pem:
                        _save_mqtt_ca("/mqtt-ca.crt", mqtt_ca_pem)
                    elif config["amms"]["transport"] == "mqtt" and not _file_exists("/mqtt-ca.crt"):
                        raise ValueError("incollare il certificato CA MQTT")
                    save(config)
                    _send_response(client, "200 OK", _page("Configurazione salvata. Riavvio in corso..."))
                    time.sleep(1)
                    import machine
                    machine.reset()
                else:
                    _send_response(client, "200 OK", _page())
            except Exception as exc:
                print("Errore portale:", exc)
                try:
                    _send_response(client, "400 Bad Request", _page("Richiesta non valida"))
                except Exception:
                    pass
            finally:
                client.close()
    finally:
        server.close()
        access_point.active(False)


AP_IP = "192.168.4.1"


def _dns_reply(packet):
    """Risposta DNS wildcard IPv4; scarta richieste malformate/non standard."""
    if len(packet) < 17 or packet[2] & 0x80 or packet[4:6] != b"\x00\x01":
        return None
    if packet[2] & 0x78:
        return None
    end = 12
    while end < len(packet):
        size = packet[end]
        if size == 0:
            end += 1
            break
        if size > 63 or end + size + 1 >= len(packet):
            return None
        end += size + 1
    if end + 4 > len(packet):
        return None
    question = packet[12:end + 4]
    ipv4 = packet[end:end + 4] == b"\x00\x01\x00\x01"
    header = packet[:2] + b"\x81\x80\x00\x01" + (
        b"\x00\x01" if ipv4 else b"\x00\x00"
    ) + b"\x00\x00\x00\x00"
    answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x00\x00\x04\xc0\xa8\x04\x01"
    return header + question + (answer if ipv4 else b"")


def _escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def _configuration_form(config):
    config = config or {}
    wifi = config.get("wifi", {})
    wu = config.get("weather_underground", {})
    return """<article><h2>Configurazione Wi-Fi e Weather Underground</h2>
<form id="configuration" method="post" action="/save">
<label>Nome rete Wi-Fi (SSID)<input name="ssid" maxlength="32" value="%s" autocomplete="off"></label>
<label>Password Wi-Fi<input name="password" type="password" maxlength="64" placeholder="Vuoto: conserva la password della stessa rete" autocomplete="new-password"></label>
<label><input type="checkbox" name="clear_wifi_password"> Rete Wi-Fi senza password</label>
<h3>Weather Underground</h3>
<label><input type="checkbox" name="wu_enabled" %s> Abilita invio dati</label>
<label>ID stazione WU<input name="wu_station_id" maxlength="64" value="%s"></label>
<label>Chiave stazione WU<input name="wu_station_key" type="password" maxlength="128" placeholder="Vuoto: conserva la chiave salvata" autocomplete="new-password"></label>
<label>Modalità<select name="wu_mode"><option value="rapidfire" %s>RapidFire</option><option value="standard" %s>Invio standard PWS</option></select></label>
<label>Intervallo invio (secondi, minimo 10)<input name="wu_interval" type="number" min="10" max="86400" value="%s"></label>
<label>Scostamento UTC per pioggia giornaliera (minuti)<input name="wu_utc_offset" type="number" min="-720" max="840" value="%s"></label>
%s
<button type="submit">Salva e riavvia</button><p id="save_status" role="status"></p>
</form><small>L'AP rimane disponibile mentre la scheda si collega al router.
Password e chiave stazione già salvate non vengono mostrate. WU usa la prima stazione meteo rilevata dopo l'avvio.</small></article>""" % (
        _escape(wifi.get("ssid", "")), "checked" if wu.get("enabled") else "",
        _escape(wu.get("station_id", "")),
        "selected" if wu.get("mode", "rapidfire") == "rapidfire" else "",
        "selected" if wu.get("mode") == "standard" else "",
        _escape(wu.get("upload_interval_seconds", 10)), _escape(wu.get("utc_offset_minutes", 60)),
        _amms_form(config.get("amms", {})))


def _amms_form(amms):
    def value(name, default=""):
        return _escape(amms.get(name, default))

    return """<h3>AMMS e MQTT/TLS</h3>
<label><input type="checkbox" name="amms_enabled" %s> Abilita invio ad AMMS</label>
<label>Trasporto<select name="transport"><option value="http" %s>HTTPS AMMS</option><option value="mqtt" %s>MQTT/TLS AMMS</option></select></label>
<label>Autenticazione<select name="auth_mode"><option value="hmac-sha256" %s>HMAC-SHA256</option><option value="bearer" %s>Token Bearer precedente (solo HTTPS)</option></select></label>
<label>ID stazione AMMS / utente MQTT<input name="station_id" maxlength="64" value="%s"></label>
<label>ID chiave HMAC<input name="key_id" maxlength="64" value="%s"></label>
<label>Chiave HMAC / password MQTT (64 cifre esadecimali)<input type="password" name="secret_hex" maxlength="64" autocomplete="new-password" placeholder="Vuoto: conserva la chiave salvata"></label>
<label>Token AMMS precedente<input type="password" name="token" maxlength="512" autocomplete="new-password" placeholder="Vuoto: conserva il token salvato"></label>
<label>URL API AMMS<input name="url" type="url" maxlength="256" value="%s"></label>
<label>Tempo massimo risposta AMMS (secondi)<input name="timeout_seconds" type="number" min="1" max="60" value="%s"></label>
<label>Intervallo AMMS (secondi)<input name="amms_interval" type="number" min="1" max="86400" value="%s"></label>
<label>Server MQTT<input name="mqtt_host" maxlength="253" value="%s"></label>
<label>Porta MQTT/TLS<input name="mqtt_port" type="number" min="1" max="65535" value="%s"></label>
<label>Mantenimento connessione MQTT (secondi)<input name="mqtt_keepalive" type="number" min="10" max="3600" value="%s"></label>
<label>Percorso CA MQTT salvato<input name="mqtt_ca_cert" maxlength="96" value="%s"></label>
<label>Certificato CA MQTT (PEM)<textarea name="mqtt_ca_pem" rows="7" maxlength="4096" placeholder="Vuoto: conserva il certificato esistente"></textarea></label>
<small>MQTT mantiene i topic e il formato AMMS originali; richiede autenticazione per stazione e CA valida.
HTTPS e MQTT sono due trasporti alternativi di AMMS. Wunderground può essere attivo contemporaneamente.</small>""" % (
        "checked" if amms.get("enabled") else "",
        "selected" if amms.get("transport") == "http" else "",
        "selected" if amms.get("transport", "mqtt") == "mqtt" else "",
        "selected" if amms.get("auth_mode", "hmac-sha256") == "hmac-sha256" else "",
        "selected" if amms.get("auth_mode") == "bearer" else "",
        value("station_id"), value("key_id"), value("url", "https://weather.iacca.ml/api/data/point"),
        value("timeout_seconds", 15), value("upload_interval_seconds", 10),
        value("mqtt_host", "weather.iacca.ml"), value("mqtt_port", 8883), value("mqtt_keepalive", 45), value("mqtt_ca_cert", "/mqtt-ca.crt"))


def _save_ap_configuration(config, form):
    candidate = {key: value.copy() for key, value in config.items()}
    wifi = candidate["wifi"]
    ssid = form.get("ssid", "")
    password = form.get("password", "")
    if len(ssid.encode("utf-8")) > 32 or len(password.encode("utf-8")) > 64:
        raise ValueError("SSID o password Wi-Fi troppo lunghi")
    if ssid != wifi.get("ssid") or password or form.get("clear_wifi_password") == "on":
        wifi["password"] = "" if form.get("clear_wifi_password") == "on" else password
    wifi["ssid"] = ssid
    wu = candidate["weather_underground"]
    wu["enabled"] = form.get("wu_enabled") == "on"
    wu["station_id"] = form.get("wu_station_id", "").strip()
    if form.get("wu_station_key"):
        wu["station_key"] = form["wu_station_key"]
    wu["mode"] = form.get("wu_mode", "rapidfire")
    wu["upload_interval_seconds"] = int(form.get("wu_interval", "10"))
    wu["utc_offset_minutes"] = int(form.get("wu_utc_offset", "60"))
    if len(wu["station_id"]) > 64 or len(wu["station_key"]) > 128:
        raise ValueError("credenziali WU troppo lunghe")
    if wu["enabled"] and not ssid:
        raise ValueError("per Weather Underground serve una rete Wi-Fi")
    validate_weather_underground(candidate)
    amms = candidate["amms"]
    amms["enabled"] = form.get("amms_enabled") == "on"
    for key in ("transport", "auth_mode", "station_id", "key_id", "url", "mqtt_host", "mqtt_ca_cert"):
        if key in form:
            amms[key] = form[key].strip()
    for key in ("secret_hex", "token"):
        if form.get(key):
            amms[key] = form[key].strip()
    amms["mqtt_port"] = int(form.get("mqtt_port", str(amms.get("mqtt_port", 8883))))
    amms["mqtt_keepalive"] = int(form.get("mqtt_keepalive", str(amms.get("mqtt_keepalive", 45))))
    amms["timeout_seconds"] = int(form.get("timeout_seconds", str(amms.get("timeout_seconds", 15))))
    amms["upload_interval_seconds"] = int(form.get("amms_interval", str(amms.get("upload_interval_seconds", 10))))
    cert_path = amms.get("mqtt_ca_cert", "/mqtt-ca.crt")
    if not cert_path.startswith("/") or ".." in cert_path or not cert_path.endswith(".crt") or len(cert_path) > 96:
        raise ValueError("percorso certificato CA non valido")
    pem = form.get("mqtt_ca_pem", "").strip()
    if pem:
        if len(pem) > 4096 or "-----BEGIN CERTIFICATE-----" not in pem or "-----END CERTIFICATE-----" not in pem:
            raise ValueError("certificato CA non valido")
        # Mantiene intatta la vecchia CA se il successivo salvataggio fallisce.
        import hashlib
        import binascii
        suffix = binascii.hexlify(hashlib.sha256(pem.encode()).digest()).decode()[:16]
        cert_path = "/mqtt-ca-" + suffix + ".crt"
        amms["mqtt_ca_cert"] = cert_path
    validate_amms(candidate, certificate_available=bool(pem) or _file_exists(cert_path))
    if pem:
        _save_mqtt_ca(cert_path, pem)
    candidate["runtime"]["mode"] = "ap"
    save(candidate)
    config.update(candidate)


def _request_complete(request):
    if b"\r\n\r\n" not in request:
        return False
    headers, body = bytes(request).split(b"\r\n\r\n", 1)
    length = 0
    seen_length = False
    for line in headers.split(b"\r\n")[1:]:
        if b":" not in line:
            raise ValueError("header HTTP non valido")
        key, value = line.split(b":", 1)
        if key.lower() == b"transfer-encoding":
            raise ValueError("transfer encoding non supportato")
        if key.lower() == b"content-length":
            if seen_length:
                raise ValueError("content length duplicato")
            seen_length = True
            length = int(value.strip())
    if length < 0 or length > 7168:
        raise ValueError("corpo HTTP troppo grande")
    return len(body) >= length


def _dashboard(config=None):
    from dashboard import render
    return render(config or {}, _configuration_form(config), _escape)


def _ap_response(request, state, config=None, service=None):
    line = request.split(b"\r\n", 1)[0].split()
    if len(line) != 3:
        raise ValueError("richiesta HTTP non valida")
    path = line[1].split(b"?", 1)[0]
    extra = "Cache-Control: no-store\r\n"
    if path in (b"/api/config", b"/api/terminal", b"/api/wifi/scan") and service is not None:
        status, kind = "200 OK", "application/json"
        try:
            if line[0] == b"POST":
                # Reject cross-origin browser mutations; local clients without Origin remain usable.
                headers = {}
                for header_line in request.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]:
                    if b":" in header_line:
                        k, v = header_line.split(b":", 1)
                        headers[k.strip().lower()] = v.strip()
                origin, host = headers.get(b"origin"), headers.get(b"host")
                if origin and (not host or origin not in (b"http://" + host, b"https://" + host)):
                    raise ValueError("Origine della richiesta non consentita")
                form = _parse_form(request.split(b"\r\n\r\n", 1)[1])
                if path == b"/api/config":
                    result = service.save_section(form, _save_ap_configuration)
                elif path == b"/api/terminal":
                    result = service.command(form.get("command", ""))
                else:
                    service.scan()
                    result = {"message": "Scansione avviata"}
            elif line[0] == b"GET" and path == b"/api/terminal":
                result = {"lines": service.lines[:]}
            elif line[0] == b"GET" and path == b"/api/wifi/scan":
                result = {"busy": service.scanning, "networks": service.networks, "message": service.scan_message}
            else:
                status, result = "405 Method Not Allowed", {"message": "Metodo non consentito"}
        except (ValueError, TypeError, UnicodeError) as exc:
            status, result = "400 Bad Request", {"message": str(exc)}
        except OSError:
            status, result = "500 Internal Server Error", {"message": "Salvataggio non riuscito; riprovare"}
        body = json.dumps(result).encode("utf-8")
    elif line[0] == b"POST" and path == b"/save" and config is not None:
        status, kind = "200 OK", "application/json"
        try:
            form = _parse_form(request.split(b"\r\n\r\n", 1)[1])
            _save_ap_configuration(config, form)
            state["restart_requested"] = time.ticks_ms()
            message = "Configurazione salvata. Riavvio: riconnettersi a Bresser Gateway."
        except (ValueError, TypeError, UnicodeError):
            status, message = "400 Bad Request", "Configurazione non valida: controllare rete, credenziali WU e intervallo."
        except OSError:
            status, message = "500 Internal Server Error", "Salvataggio su flash non riuscito; configurazione precedente conservata."
        body = json.dumps({"message": message}).encode("utf-8")
    elif line[0] != b"GET":
        status, kind, body = "405 Method Not Allowed", "text/plain", b"Solo GET"
        extra += "Allow: GET\r\n"
    elif path == b"/api/readings":
        status, kind = "200 OK", "application/json"
        body = json.dumps(state).encode("utf-8")
    elif path == b"/":
        status, kind = "200 OK", "text/html; charset=utf-8"
        body = _dashboard(config).encode("utf-8")
    else:
        # Include probe Android, Apple e Windows: rimangono captive.
        status, kind, body = "302 Found", "text/plain", b"Bresser Gateway"
        extra += "Location: http://%s/\r\n" % AP_IP
    header = "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n%sConnection: close\r\n\r\n" % (
        status, kind, len(body), extra
    )
    return header.encode("utf-8") + body


def run_ap(config, radio, radio_error=""):
    """AP permanente: DNS captive, HTTP e radio serviti nello stesso ciclo."""
    wlan = station()
    wifi = config.get("wifi", {})
    wlan.active(bool(wifi.get("ssid")))
    ap = network.WLAN(AP_IF)
    ap.active(True)
    ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))
    ap.config(ssid=config["runtime"].get("ap_ssid", "Bresser Gateway"), security=0)
    server = socket.socket()
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    clients = {}
    poller = select.poll()
    state = {"sensors": {}, "received": 0, "age_seconds": None,
             "firmware_version": FIRMWARE_VERSION, "firmware_stage": FIRMWARE_STAGE,
             "sensor_id": None, "rssi": None, "battery_ok": None, "error": radio_error,
             "model": "", "protocol": "", "unrecognized": 0, "stations": {},
             "wifi_status": "non configurato", "wu_status": "disabilitato"}
    receiver = None
    if not radio_error:
        try:
            receiver = AutoReceiver(radio)
        except Exception as exc:
            radio_error = str(exc)
            state["error"] = radio_error
            print("Errore ricevitore:", radio_error)
    try:
        led = ReceiveLED(config["runtime"])
    except Exception as exc:
        led = None
        print("LED non disponibile:", exc)
    from dashboard_service import DashboardService
    service = DashboardService(config, wlan, state)
    service.radio = radio
    uplink = Uplink(config, wlan)
    started = time.ticks_ms()
    uptime_ms = 0
    previous_tick = started
    station_seen = {}
    last_state_refresh = None
    last_connect = None
    last_reading = None
    last_report = None
    interval = max(1, min(100, int(config["runtime"].get("poll_interval_ms", 25))))

    def close_client(client):
        poller.unregister(client)
        clients.pop(client, None)
        client.close()

    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", 80))
        server.listen(2)
        server.setblocking(False)
        dns.bind(("0.0.0.0", 53))
        dns.setblocking(False)
        poller.register(server, select.POLLIN)
        poller.register(dns, select.POLLIN)
        print("AP:", config["runtime"].get("ap_ssid", "Bresser Gateway"))
        print("Captive portal: http://%s | seriale 115200 baud" % AP_IP)
        print("Autoriconoscimento Bresser 5-in-1 / 6-in-1 / 7-in-1 e varianti; 868.3 MHz FSK")
        while True:
            now = time.ticks_ms()
            uptime_ms += max(0, time.ticks_diff(now, previous_tick))
            previous_tick = now
            state["uptime_seconds"] = uptime_ms // 1000
            interval = max(1, min(100, int(config["runtime"].get("poll_interval_ms", 25))))
            if last_state_refresh is None or time.ticks_diff(now, last_state_refresh) >= 1000:
                last_state_refresh = now
                service.tick(now, bool(wifi.get("ssid")) and wlan.isconnected())
                try:
                    import esp32
                    temperature = getattr(esp32, "mcu_temperature", None)
                    state["core_temperature"] = temperature() if temperature else (esp32.raw_temperature() - 32) / 1.8
                except Exception:
                    state["core_temperature"] = None
            if led:
                led.tick(now)
            if wifi.get("ssid"):
                connected = wlan.isconnected()
                state["wifi_status"] = "connesso" if connected else "connessione in corso"
                if not connected and not service.scanning and (last_connect is None or time.ticks_diff(now, last_connect) >= 30000):
                    last_connect = now
                    try:
                        wlan.disconnect()
                        wlan.connect(wifi["ssid"], wifi.get("password", ""))
                        print("Connessione Wi-Fi a", wifi["ssid"], "| AP sempre attivo")
                    except OSError:
                        state["wifi_status"] = "errore connessione"
            state["wu_status"] = uplink.status
            state["amms_status"] = uplink.amms_status
            if not radio_error:
                try:
                    reading = receiver.poll()
                    if reading is not None:
                        if led:
                            led.pulse(now)
                        if reading.get("error"):
                            state["unrecognized"] += 1
                            state["error"] = reading["error"]
                            print("ERRORE RF:", json.dumps(reading))
                            service.log("ERRORE RF: " + json.dumps(reading))
                        else:
                            state["error"] = ""
                            state["sensors"] = canonical_sensor_values(reading)
                            for key in ("sensor_id", "rssi", "battery_ok", "model", "protocol"):
                                state[key] = reading.get(key)
                            station_key = "%s:%s:%s" % (reading.get("protocol"), reading.get("sensor_id"), reading.get("channel", 0))
                            if station_key not in state["stations"] and len(state["stations"]) >= 8:
                                oldest = next(iter(state["stations"]))
                                del state["stations"][oldest]
                                station_seen.pop(oldest, None)
                            old_battery = state["stations"].get(station_key, {}).get("battery_ok")
                            if reading.get("battery_ok") is not None and reading["battery_ok"] != old_battery:
                                service.log("Batteria %s: %s (stato RF)" % (station_key, "OK" if reading["battery_ok"] else "LOW"))
                            state["stations"][station_key] = {"model": reading.get("model"), "rssi": reading.get("rssi"),
                                "battery_ok": reading.get("battery_ok"), "sensors": canonical_sensor_values(reading),
                                "received": state["received"] + 1, "age_seconds": 0}
                            station_seen[station_key] = now
                            state["received"] += 1
                            last_reading = now
                            state["age_seconds"] = 0
                            print("Ricevuto:", json.dumps(reading))
                            service.log("Ricevuto: " + json.dumps(reading))
                            uplink.submit(reading)
                except Exception as exc:
                    radio_error = str(exc)
                    state["error"] = radio_error
                    print("Errore radio:", radio_error)
            for key, seen in station_seen.items():
                state["stations"][key]["age_seconds"] = time.ticks_diff(now, seen) // 1000
            if last_reading is not None:
                state["age_seconds"] = time.ticks_diff(now, last_reading) // 1000
            if service.monitor_interval and (last_report is None or time.ticks_diff(now, last_report) >= service.monitor_interval * 1000):
                last_report = now
                print("Stato firmware %s | RF: validi=%d errori=%d ultima=%s s | Wi-Fi: %s" % (
                    FIRMWARE_VERSION, state["received"], state["unrecognized"],
                    str(state["age_seconds"]), state["wifi_status"]))
                service.log("Stato firmware %s | RF validi=%d errori=%d | Wi-Fi: %s | AMMS: %s | WU: %s" % (
                    FIRMWARE_VERSION, state["received"], state["unrecognized"], state["wifi_status"], state.get("amms_status"), state["wu_status"]))
                if not radio_error and callable(getattr(radio, "diagnostics", None)):
                    try:
                        diagnostics = radio.diagnostics()
                        encoded = json.dumps(diagnostics)
                        state["radio_diagnostics"] = diagnostics
                        print("Diagnostica RF:", encoded)
                    except Exception as exc:
                        print("Diagnostica RF non disponibile:", exc)
                elif radio_error:
                    print("ERRORE ricevitore:", radio_error)
                if last_reading is None:
                    print("In ascolto: nessun pacchetto Bresser valido ricevuto finora")
            for sock, event in poller.poll(interval):
                if sock == dns:
                    try:
                        packet, address = dns.recvfrom(512)
                        answer = _dns_reply(packet)
                        if answer:
                            dns.sendto(answer, address)
                    except OSError:
                        pass
                elif sock == server:
                    try:
                        client, _ = server.accept()
                        if len(clients) >= 2:
                            client.close()
                            continue
                        client.setblocking(False)
                        clients[client] = [bytearray(), now, None, 0]
                        poller.register(client, select.POLLIN)
                    except OSError:
                        pass
                elif sock in clients:
                    item = clients[sock]
                    try:
                        if event & (select.POLLERR | select.POLLHUP):
                            close_client(sock)
                        elif item[2] is None:
                            chunk = sock.recv(1024)
                            if not chunk:
                                close_client(sock)
                                continue
                            item[0].extend(chunk)
                            if len(item[0]) > 8192:
                                close_client(sock)
                            elif _request_complete(item[0]):
                                item[2] = _ap_response(bytes(item[0]), state, config, service)
                                poller.modify(sock, select.POLLOUT)
                        elif event & select.POLLOUT:
                            sent = sock.send(item[2][item[3]:item[3] + 2048])
                            item[3] += sent
                            if not sent or item[3] >= len(item[2]):
                                close_client(sock)
                    except OSError as exc:
                        # Una socket non bloccante puo non essere pronta anche
                        # dopo poll: riproviamo senza troncare la risposta HTTP.
                        if exc.args and exc.args[0] in (11, 35, 10035):
                            continue
                        if sock in clients:
                            close_client(sock)
                    except ValueError:
                        if sock in clients:
                            close_client(sock)
            for client in list(clients):
                if time.ticks_diff(time.ticks_ms(), clients[client][1]) > 3000:
                    close_client(client)
            if "restart_requested" in state and not clients and time.ticks_diff(now, state["restart_requested"]) >= 1500:
                import machine
                machine.reset()
    finally:
        uplink.stop()
        if led:
            led.off()
        for client in list(clients):
            close_client(client)
        server.close()
        dns.close()
        ap.active(False)

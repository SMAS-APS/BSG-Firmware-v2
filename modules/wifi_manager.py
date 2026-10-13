import socket
import time
import json
import select
import sys
import gc

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
    from dashboard_forms import configuration_form
    return configuration_form(config)


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
    wu["station_id"] = form.get("wu_station_id", wu.get("station_id", "")).strip()
    if form.get("wu_station_key"):
        wu["station_key"] = form["wu_station_key"]
    wu["mode"] = form.get("wu_mode", wu.get("mode", "rapidfire"))
    wu["upload_interval_seconds"] = int(form.get("wu_interval", wu.get("upload_interval_seconds", 10)))
    wu["utc_offset_minutes"] = int(form.get("wu_utc_offset", wu.get("utc_offset_minutes", 60)))
    if len(wu["station_id"]) > 64 or len(wu["station_key"]) > 128:
        raise ValueError("credenziali WU troppo lunghe")
    if wu["enabled"] and not ssid:
        raise ValueError("per Weather Underground serve una rete Wi-Fi")
    validate_weather_underground(candidate)
    amms = candidate["amms"]
    amms["enabled"] = form.get("amms_enabled") == "on"
    for key in ("transport", "auth_mode", "station_id", "key_id", "url", "mqtt_host", "mqtt_ca_cert"):
        if key in form:
            value = form[key].strip()
            if key == "mqtt_ca_cert" and not value:
                continue  # Blank optional path keeps the configured/default CA.
            amms[key] = value
    for key in ("secret_hex", "token"):
        if form.get(key):
            amms[key] = form[key].strip()
    amms["mqtt_port"] = int(form.get("mqtt_port", str(amms.get("mqtt_port", 8883))))
    amms["mqtt_keepalive"] = int(form.get("mqtt_keepalive", str(amms.get("mqtt_keepalive", 45))))
    amms["timeout_seconds"] = int(form.get("timeout_seconds", str(amms.get("timeout_seconds", 15))))
    amms["upload_interval_seconds"] = int(form.get("amms_interval", str(amms.get("upload_interval_seconds", 10))))
    cert_path = amms.get("mqtt_ca_cert") or "/mqtt-ca.crt"
    amms["mqtt_ca_cert"] = cert_path
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


class _HTTPStream:
    def __init__(self, parts):
        self.parts = iter(parts)
        self.pending = None
        self.offset = 0

    def send(self, client):
        if self.pending is None:
            try:
                self.pending = memoryview(next(self.parts))
                self.offset = 0
            except StopIteration:
                return True
        sent = client.send(self.pending[self.offset:])
        if not sent:
            return True
        self.offset += sent
        if self.offset == len(self.pending):
            self.pending = None
        return False

    def close(self):
        self.pending = None
        close = getattr(self.parts, 'close', None)
        if close:
            close()


def _open_asset(name):
    for directory in sys.path:
        try:
            return open(directory.rstrip('/') + '/' + name, 'rb')
        except OSError:
            pass
    filename = globals().get('__file__', '').replace('\\', '/')
    if '/modules/' in filename:
        return open(filename.rsplit('/modules/', 1)[0] + '/.pio/web/' + name, 'rb')
    raise OSError(2, 'dashboard asset missing; repeat USB deploy')


def _dashboard_parts(request):
    with _open_asset('dashboard.etag') as version:
        etag = b'W/"' + version.read(64) + b'"'
    if b'if-none-match: ' + etag.lower() in request.lower():
        yield b'HTTP/1.1 304 Not Modified\r\nCache-Control: no-cache\r\nVary: Accept-Encoding\r\nETag: ' + etag + b'\r\nConnection: close\r\n\r\n'
        return
    compressed = False
    for line in request.lower().split(b'\r\n'):
        if line.startswith(b'accept-encoding:') and b'gzip' in line:
            compressed = True
    with _open_asset('dashboard.html.gz' if compressed else 'dashboard.static.html') as source:
        size = source.seek(0, 2)
        source.seek(0)
        header = ('HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n'
                  'Content-Length: %d\r\nCache-Control: no-cache\r\nVary: Accept-Encoding\r\n'
                  'Connection: close\r\n' % size).encode()
        yield header + b'ETag: ' + etag + b'\r\n' + (b'Content-Encoding: gzip\r\n' if compressed else b'') + b'\r\n'
        while True:
            block = source.read(512)
            if not block:
                return
            yield block


def _iter_json(value):
    if isinstance(value, dict):
        yield b'{'
        for index, (key, item) in enumerate(tuple(value.items())):
            if index:
                yield b','
            yield json.dumps(key).encode('utf-8')
            yield b':'
            yield from _iter_json(item)
        yield b'}'
    elif isinstance(value, (list, tuple)):
        yield b'['
        for index, item in enumerate(tuple(value)):
            if index:
                yield b','
            yield from _iter_json(item)
        yield b']'
    else:
        yield json.dumps(value).encode('utf-8')


def _json_parts(status, value):
    yield ('HTTP/1.1 %s\r\nContent-Type: application/json\r\n'
           'Cache-Control: no-store\r\nConnection: close\r\n\r\n' % status).encode()
    buffer = bytearray()
    for fragment in _iter_json(value):
        buffer.extend(fragment)
        if len(buffer) >= 512:
            view = memoryview(buffer)
            for offset in range(0, len(view), 512):
                yield view[offset:offset + 512]
            view = None
            buffer = bytearray()
    if buffer:
        yield buffer


def _ap_response(request, state, config=None, service=None, stream=False):
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
                result = {"lines": service.lines}
            elif line[0] == b"GET" and path == b"/api/wifi/scan":
                result = {"busy": service.scanning, "networks": service.networks, "message": service.scan_message}
            else:
                status, result = "405 Method Not Allowed", {"message": "Metodo non consentito"}
        except (ValueError, TypeError, UnicodeError) as exc:
            status, result = "400 Bad Request", {"message": str(exc)}
        except OSError:
            status, result = "500 Internal Server Error", {"message": "Salvataggio non riuscito; riprovare"}
        if stream:
            return _HTTPStream(_json_parts(status, result))
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
        if stream:
            return _HTTPStream(_json_parts('200 OK', state))
        status, kind = "200 OK", "application/json"
        body = json.dumps(state).encode("utf-8")
    elif path == b'/api/settings' and service is not None:
        status = '200 OK'
        result = service.public_settings()
        if stream:
            return _HTTPStream(_json_parts(status, result))
        kind, body = 'application/json', json.dumps(result).encode('utf-8')
    elif path == b'/favicon.ico':
        status, kind, body = '204 No Content', 'image/x-icon', b''
    elif path == b"/":
        if stream:
            return _HTTPStream(_dashboard_parts(request))
        status, kind = "200 OK", "text/html; charset=utf-8"
        body = _dashboard(config).encode("utf-8")
    else:
        # Include probe Android, Apple e Windows: rimangono captive.
        status, kind, body = "302 Found", "text/plain", b"Bresser Gateway"
        target = AP_IP if state.get('ap_active', True) else state.get('network', {}).get('ip')
        extra += "Location: %s\r\n" % ('http://%s/' % target if target else '/')
    header = "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n%sConnection: close\r\n\r\n" % (
        status, kind, len(body), extra
    )
    return header.encode("utf-8") + body


def run_ap(config, radio, radio_error=""):
    """AP di recupero automatico; HTTP e radio restano attivi sulla rete STA."""
    wlan = station()
    wifi = config.get("wifi", {})
    wlan.active(bool(wifi.get("ssid")))
    if wifi.get('ssid') and hasattr(network.WLAN, 'PM_NONE'):
        wlan.config(pm=network.WLAN.PM_NONE)
    ap = network.WLAN(AP_IF)
    ap.active(True)
    ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))
    ap.config(ssid=config["runtime"].get("ap_ssid", "Bresser Gateway"), security=0, channel=1, max_clients=4)
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
    from wifi_recovery import WifiRecovery
    from serial_commands import SerialCommands
    recovery = WifiRecovery(config, wlan, ap)
    serial_commands = SerialCommands(config, recovery, service)
    serial_input = getattr(sys.stdin, 'buffer', sys.stdin)
    uplink = Uplink(config, wlan)
    from ota_runtime import mark as mark_ota_health, status as ota_status, start_updater, tick as ota_tick
    updater = start_updater(config)
    gc.collect()
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
        item = clients.pop(client, None)
        if item and isinstance(item[2], _HTTPStream):
            item[2].close()
        client.close()

    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", 80))
        server.listen(6)
        server.setblocking(False)
        dns.bind(("0.0.0.0", 53))
        dns.setblocking(False)
        poller.register(server, select.POLLIN)
        poller.register(dns, select.POLLIN)
        mark_ota_health("network")
        try:
            poller.register(serial_input, select.POLLIN)
            print('Comandi seriali pronti: config per impostare SSID e password; help per i comandi.')
        except (OSError, TypeError):
            serial_input = None
            print('Ingresso seriale non disponibile su questa piattaforma')
        print("AP:", config["runtime"].get("ap_ssid", "Bresser Gateway"))
        print("Captive portal: http://%s | seriale 115200 baud" % AP_IP)
        print("Autoriconoscimento Bresser 5-in-1 / 6-in-1 / 7-in-1 e varianti; 868.3 MHz FSK")
        while True:
            now = time.ticks_ms()
            ota_tick(now)
            uptime_ms += max(0, time.ticks_diff(now, previous_tick))
            previous_tick = now
            state["uptime_seconds"] = uptime_ms // 1000
            interval = max(1, min(100, int(config["runtime"].get("poll_interval_ms", 25))))
            wifi = config.get("wifi", {})
            state["wifi_status"] = recovery.tick(now, service.scanning)
            state["ap_active"] = recovery.ap_enabled
            if not recovery.ap_enabled and dns is not None:
                poller.unregister(dns)
                dns.close()
                dns = None
                gc.collect()
            elif recovery.ap_enabled and dns is None:
                candidate_dns = None
                try:
                    candidate_dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    candidate_dns.bind(("0.0.0.0", 53))
                    candidate_dns.setblocking(False)
                    poller.register(candidate_dns, select.POLLIN)
                    dns = candidate_dns
                    candidate_dns = None
                except OSError:
                    if candidate_dns is not None:
                        candidate_dns.close()
                    print('DNS captive non disponibile; AP e HTTP attivi, riprovo')
            if last_state_refresh is None or time.ticks_diff(now, last_state_refresh) >= 1000:
                last_state_refresh = now
                service.tick(now, bool(wifi.get("ssid")) and wlan.isconnected())
                state["ota"] = ota_status()
                state["ota"]["agent_status"] = updater.status if updater else "disabilitato"
                try:
                    import esp32
                    temperature = getattr(esp32, "mcu_temperature", None)
                    state["core_temperature"] = temperature() if temperature else (esp32.raw_temperature() - 32) / 1.8
                except Exception:
                    state["core_temperature"] = None
            if led:
                led.tick(now)
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
                            if not serial_commands.configuring:
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
                            if not serial_commands.configuring:
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
            if not serial_commands.configuring and service.monitor_interval and (last_report is None or time.ticks_diff(now, last_report) >= service.monitor_interval * 1000):
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
                if sock is serial_input:
                    try:
                        serial_commands.feed(serial_input.read(1))
                    except (OSError, ValueError):
                        print('Errore ingresso seriale; ciclo AP mantenuto attivo')
                elif sock == dns:
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
                        client.setblocking(False)
                        if len(clients) >= 6:
                            try:
                                client.send(b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nRetry-After: 1\r\nConnection: close\r\n\r\n{"message":"Centralina occupata; riprovare tra pochi secondi."}')
                            except OSError:
                                pass
                            client.close()
                            continue
                        if hasattr(socket, 'TCP_NODELAY'):
                            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
                            item[1] = time.ticks_ms()
                            buffered = sum(len(entry[0]) for entry in clients.values() if entry[0] is not None)
                            if len(item[0]) > 8192 or buffered > 12288:
                                close_client(sock)
                            elif _request_complete(item[0]):
                                gc.collect()
                                item[2] = _ap_response(bytes(item[0]), state, config, service, stream=True)
                                item[0] = None
                                # Every response uses bounded chunks; a slow page
                                # must not block telemetry or configuration requests.
                                poller.modify(sock, select.POLLOUT)
                        elif event & select.POLLOUT:
                            if isinstance(item[2], _HTTPStream):
                                done = False
                                for write in range(4):
                                    done = item[2].send(sock)
                                    if done:
                                        break
                            else:
                                sent = sock.send(memoryview(item[2])[item[3]:item[3] + 2048])
                                item[3] += sent
                                done = not sent or item[3] >= len(item[2])
                            item[1] = time.ticks_ms()
                            if done:
                                close_client(sock)
                    except OSError as exc:
                        # Una socket non bloccante puo non essere pronta anche
                        # dopo poll: riproviamo senza troncare la risposta HTTP.
                        if exc.args and exc.args[0] in (11, 35, 10035):
                            continue
                        if sock in clients:
                            close_client(sock)
                    except MemoryError:
                        if sock in clients:
                            close_client(sock)
                        gc.collect()
                        print('Memoria insufficiente per HTTP; rete e comandi seriali mantenuti attivi; heap:', getattr(gc, 'mem_free', lambda: 0)())
                    except Exception as exc:
                        # A failed page generation (including heap exhaustion) must not tear down the AP.
                        print('Errore richiesta HTTP:', type(exc).__name__, '| AP e seriale ancora attivi')
                        service.log('Errore HTTP: ' + type(exc).__name__)
                        if sock in clients:
                            close_client(sock)
                        gc.collect()
            for client in list(clients):
                if time.ticks_diff(time.ticks_ms(), clients[client][1]) > 10000:
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
        if dns is not None:
            dns.close()
        ap.active(False)

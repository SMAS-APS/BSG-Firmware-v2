import socket
import time
import json
import select

import network

from config_store import save, validate_weather_underground
from wu_support import canonical_sensor_values


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
<label>Token AMMS legacy<input name=\"token\" type=\"password\"></label>
<label>URL API<input name=\"url\" value=\"https://weather.iacca.ml/api/data/point\" required></label>
<label>Host MQTT<input name=\"mqtt_host\" value=\"weather.iacca.ml\"></label>
<label>Porta MQTT/TLS<input name=\"mqtt_port\" value=\"8883\" inputmode=\"numeric\"></label>
<label>Certificato CA MQTT (PEM)<textarea name=\"mqtt_ca_pem\" rows=\"7\" placeholder=\"-----BEGIN CERTIFICATE-----\"></textarea></label>
<h2>Weather Underground</h2>
<label><input name=\"wu_enabled\" type=\"checkbox\" style=\"width:auto\"> Abilita upload WU</label>
<label>Station ID WU<input name=\"wu_station_id\"></label>
<label>Station key WU<input name=\"wu_station_key\" type=\"password\"></label>
<label>Modalita' WU<select name=\"wu_mode\">
<option value=\"rapidfire\">RapidFire</option><option value=\"standard\">PWS standard</option>
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
    import os
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(temporary_path, path)


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


def _dashboard():
    return """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bresser Gateway</title><style>
body{font-family:system-ui,sans-serif;background:#edf2f6;color:#172b3a;max-width:900px;margin:auto;padding:24px}
h1{margin-bottom:4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
article{background:white;border-radius:12px;padding:20px}strong{display:block;font-size:28px;margin-top:10px}
#status{padding:16px;background:white;border-radius:12px}small{color:#526777}</style></head>
<body><h1>Bresser Gateway</h1><p>Dati locali della stazione · Access Point</p>
<p id="status">In attesa del ricevitore...</p><div class="grid">
<article>Temperatura<strong id="temperature">—</strong><small>°C</small></article>
<article>Umidità<strong id="humidity">—</strong><small>%</small></article>
<article>Vento<strong id="wind_speed">—</strong><small>km/h</small></article>
<article>Raffica<strong id="wind_gust">—</strong><small>km/h</small></article>
<article>Direzione<strong id="wind_direction">—</strong><small>gradi</small></article>
<article>Pioggia cumulativa<strong id="precipitation">—</strong><small>mm · contatore sensore</small></article>
</div><p id="details"></p><small>Indirizzo locale: http://192.168.4.1 · Serial Monitor: 115200 baud</small>
<script>
async function refresh(){try{
const r=await fetch('/api/readings',{cache:'no-store'});if(!r.ok)throw Error('HTTP');const d=await r.json();
for(const k of ['temperature','humidity','wind_speed','wind_gust','wind_direction','precipitation']){
const v=d.sensors[k];document.getElementById(k).textContent=v==null?'—':Number(v).toLocaleString('it-IT',{maximumFractionDigits:1});}
document.getElementById('status').textContent=d.error?'Errore radio: '+d.error:d.age_seconds==null?'In attesa di un pacchetto Bresser 5-in-1':
'Ultima ricezione: '+d.age_seconds+' s fa'+(d.age_seconds>120?' · Dati non aggiornati':'');
document.getElementById('details').textContent='Pacchetti validi: '+d.received+(d.sensor_id==null?'':' · Sensore: '+d.sensor_id)+
(d.rssi==null?'':' · RSSI: '+d.rssi+' dBm')+(d.battery_ok==null?'':d.battery_ok?' · Batteria OK':' · Batteria scarica');
}catch(e){document.getElementById('status').textContent='Connessione al gateway interrotta';}finally{setTimeout(refresh,2000);}}
refresh();</script></body></html>"""


def _ap_response(request, state):
    line = request.split(b"\r\n", 1)[0].split()
    if len(line) != 3:
        raise ValueError("richiesta HTTP non valida")
    path = line[1].split(b"?", 1)[0]
    extra = "Cache-Control: no-store\r\n"
    if line[0] != b"GET":
        status, kind, body = "405 Method Not Allowed", "text/plain", b"Solo GET"
        extra += "Allow: GET\r\n"
    elif path == b"/api/readings":
        status, kind = "200 OK", "application/json"
        body = json.dumps(state).encode("utf-8")
    elif path == b"/":
        status, kind = "200 OK", "text/html; charset=utf-8"
        body = _dashboard().encode("utf-8")
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
    station().active(False)
    ap = network.WLAN(AP_IF)
    ap.active(True)
    ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))
    ap.config(ssid=config["runtime"].get("ap_ssid", "Bresser Gateway"), security=0)
    server = socket.socket()
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    clients = {}
    poller = select.poll()
    state = {"sensors": {}, "received": 0, "age_seconds": None,
             "sensor_id": None, "rssi": None, "battery_ok": None, "error": radio_error}
    last_reading = None
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
        print("In attesa di pacchetti Bresser 5-in-1")
        while True:
            now = time.ticks_ms()
            if not radio_error:
                try:
                    reading = radio.poll()
                    if reading is not None:
                        state["sensors"] = canonical_sensor_values(reading)
                        for key in ("sensor_id", "rssi", "battery_ok"):
                            state[key] = reading.get(key)
                        state["received"] += 1
                        last_reading = now
                        state["age_seconds"] = 0
                        print("Ricevuto:", json.dumps(state))
                except Exception as exc:
                    radio_error = str(exc)
                    state["error"] = radio_error
                    print("Errore radio:", radio_error)
            if last_reading is not None:
                state["age_seconds"] = time.ticks_diff(now, last_reading) // 1000
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
                            if len(item[0]) > 4096:
                                close_client(sock)
                            elif b"\r\n\r\n" in item[0]:
                                item[2] = _ap_response(bytes(item[0]), state)
                                poller.modify(sock, select.POLLOUT)
                        elif event & select.POLLOUT:
                            sent = sock.send(item[2][item[3]:])
                            item[3] += sent
                            if not sent or item[3] >= len(item[2]):
                                close_client(sock)
                    except (OSError, ValueError):
                        if sock in clients:
                            close_client(sock)
            for client in list(clients):
                if time.ticks_diff(time.ticks_ms(), clients[client][1]) > 3000:
                    close_client(client)
    finally:
        for client in list(clients):
            close_client(client)
        server.close()
        dns.close()
        ap.active(False)

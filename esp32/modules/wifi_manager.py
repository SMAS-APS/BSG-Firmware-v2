import socket
import time

import network

from config_store import save


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
label{display:block;margin-top:1rem}input{width:100%;box-sizing:border-box;padding:.65rem}
button{margin-top:1.4rem;padding:.7rem 1rem}.message{color:#075}</style></head>
<body><h1>Bresser Gateway</h1><p>Configura rete e accesso AMMS.</p>
<p class=\"message\">%s</p>
<form method=\"post\" action=\"/save\">
<label>Nome rete Wi-Fi<input name=\"ssid\" required></label>
<label>Password Wi-Fi<input name=\"password\" type=\"password\"></label>
<label>Token AMMS<input name=\"token\" type=\"password\" required></label>
<label>URL API<input name=\"url\" value=\"https://weather.iacca.ml/api/data/point\" required></label>
<button type=\"submit\">Salva e riavvia</button></form></body></html>""" % message


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
                    config["amms"]["token"] = form.get("token", "")
                    config["amms"]["url"] = form.get("url", config["amms"]["url"])
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

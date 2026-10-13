"""Host-side form rendering; excluded from the live HTTP request path."""
def _escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def configuration_form(config):
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



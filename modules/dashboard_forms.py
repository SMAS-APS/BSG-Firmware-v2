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
        _amms_form(config.get("amms", {}), config.get("activation", {})))


def _amms_form(amms, activation=None):
    def value(name, default=""):
        return _escape(amms.get(name, default))

    active = bool(amms.get("station_id") and amms.get("key_id") and amms.get("secret_hex"))
    return """<h3>AMMS e MQTT/TLS</h3>
<p class="hint">Stato: <strong>%s</strong></p>
<label>Chiave di attivazione<input type="password" name="activation_key" maxlength="64" autocomplete="one-time-code" placeholder="AMMS-XXXX-XXXX-XXXX-XXXX-XXXX"></label>
<details><summary>Opzioni avanzate</summary>
<label>Server AMMS<input name="activation_server_url" type="url" maxlength="256" value="%s"></label>
</details>
<small>Inserisci soltanto la chiave generata dalla console. Identità HMAC, broker MQTT e certificato CA vengono configurati automaticamente. Le credenziali già attive restano valide.</small>""" % (
        "attiva come " + value("station_id") if active else "non attivata",
        _escape((activation or {}).get("server_url", "https://151.242.0.96")),
    )



"""Offline dashboard served by both the AP and station interfaces."""



def _values(config, integration_form, escape):
    from station_clock import DEFAULT_CLOCK, ZONES
    settings = dict(DEFAULT_CLOCK)
    settings.update(config.get("clock", {}))
    def field(name, label, kind="text", extra=""):
        return '<label>%s<input name="%s" type="%s" value="%s" %s></label>' % (label, name, kind, escape(settings[name]), extra)
    fields = field("ntp_server", "Server NTP", extra='maxlength="253" required')
    zone_labels = {'Europe/Rome': 'Europa/Roma', 'Europe/Paris': 'Europa/Parigi', 'Europe/Berlin': 'Europa/Berlino', 'Europe/Madrid': 'Europa/Madrid', 'Europe/London': 'Europa/Londra', 'Europe/Athens': 'Europa/Atene', 'UTC': 'UTC', 'Custom': 'Personalizzato'}
    fields += '<label>Fuso orario<select name="timezone">' + ''.join('<option value="%s" %s>%s</option>' % (zone, 'selected' if settings['timezone'] == zone else '', zone_labels[zone]) for zone in list(ZONES) + ['Custom']) + '</select></label>'
    fields += field("utc_offset_minutes", "Scostamento UTC (minuti, fuso personalizzato)", "number", 'min="-720" max="840"')
    fields += field("sync_interval_seconds", "Sincronizzazione NTP (secondi)", "number", 'min="60" max="86400"')
    for name, label in (("ntp_enabled", "NTP attivo"), ("dst_auto", "Ora legale/solare automatica (fusi europei)")):
        fields += '<label class="wide"><input type="checkbox" name="%s" %s> %s</label>' % (name, 'checked' if settings[name] else '', label)
    runtime = config.get('runtime', {})
    integrations = integration_form[integration_form.index('<h3>Weather Underground</h3>'):integration_form.index('<button type="submit">')]
    wu, amms = integrations.split('<h3>AMMS e MQTT/TLS</h3>', 1)
    # One timezone controls both displayed time and daily rainfall; preserve the legacy field in storage.
    offset_start = wu.index('<label>Scostamento UTC per pioggia giornaliera')
    offset_end = wu.index('</label>', offset_start) + len('</label>')
    wu = wu[:offset_start] + '<input type="hidden" name="wu_utc_offset" value="%s"><p class="hint">La pioggia giornaliera usa il fuso orario e il cambio automatico dell’ora impostati in Data e ora.</p>' % escape(config.get('weather_underground', {}).get('utc_offset_minutes', 60)) + wu[offset_end:]
    amms, mqtt = amms.split('<label>Server MQTT', 1)
    mqtt = '<label>Server MQTT' + mqtt
    note_start = mqtt.index('<small>MQTT mantiene')
    mqtt = mqtt[:note_start] + '<p class="hint">MQTT usa ID stazione e chiave HMAC configurati nella colonna AMMS. Seleziona MQTT/TLS nel campo Trasporto per utilizzare questo servizio.</p>'
    wu = wu.replace('<h3>Weather Underground</h3>', '<h2>Wunderground</h2>')
    integrations = ('<form id="configuration"><input name="section" type="hidden" value="integrations">'
        '<div class="grid integration-grid">'
        '<article id="service-wunderground" class="panel">' + wu + '</article>'
        '<article id="service-amms" class="panel"><h2>AMMS</h2>' + amms + '</article>'
        '<article id="service-mqtt" class="panel"><h2>MQTT</h2>' + mqtt + '</article></div>'
        '<p><button class="primary">Salva servizi</button></p>'
        '<p class="hint">Campi segreti vuoti: conserva i valori salvati. Le modifiche ai servizi richiedono il riavvio.</p></form>')
    options = ''.join('<option value="%d" %s>%s</option>' % (n, 'selected' if n == runtime.get('serial_interval_seconds', 10) else '', str(n)+' s' if n else 'Disattivato') for n in (0, 1, 5, 10, 30, 60))
    wifi = config.get('wifi', {})
    return {
        '__SSID__': escape(wifi.get('ssid', '')),
        '__CLOCK_FIELDS__': fields,
        '__INTEGRATIONS__': integrations,
        '__POLL__': escape(runtime.get('poll_interval_ms', 25)),
        '__HIDDEN_CHECKED__': 'checked' if wifi.get('hidden') else '',
        '__OPEN_CHECKED__': 'checked' if wifi.get('ssid') and not wifi.get('password') else '',
        '__SERIAL_OPTIONS__': options,
    }


def _open_template():
    import sys
    for directory in sys.path:
        try:
            return open(directory.rstrip('/') + '/dashboard.html', 'rb')
        except OSError:
            pass
    filename = globals().get('__file__', '').replace('\\', '/')
    if '/modules/' in filename:
        return open(filename.rsplit('/modules/', 1)[0] + '/dashboard.html', 'rb')
    return open('dashboard.html', 'rb')


def iter_render(config, integration_form, escape):
    import gc
    gc.collect()
    values = {key.encode(): value.encode('utf-8')
              for key, value in _values(config, integration_form, escape).items()}
    integration_form = config = escape = None
    gc.collect()
    # Keep enough bytes to recognize placeholders crossing a flash read.
    with _open_template() as source:
        pending = b''
        while True:
            block = source.read(512)
            pending += block
            if not block:
                cut = len(pending)
            elif len(pending) < 1024:
                continue
            else:
                cut = 512
                for token in values:
                    position = pending.find(token, max(0, cut - len(token)), cut)
                    if position >= 0 and position + len(token) > cut:
                        cut = position
            part, pending = pending[:cut], pending[cut:]
            # Send replacements separately instead of allocating a larger page
            # fragment. Release each generated field as soon as it is sent.
            while part:
                first = len(part)
                selected = None
                for token in values:
                    position = part.find(token)
                    if 0 <= position < first:
                        first, selected = position, token
                if first:
                    view = memoryview(part)
                    for offset in range(0, first, 512):
                        yield view[offset:min(offset + 512, first)]
                    view = None
                if selected is None:
                    break
                value = memoryview(values.pop(selected))
                for offset in range(0, len(value), 512):
                    yield value[offset:offset + 512]
                value = None
                part = part[first + len(selected):]
            if not block:
                return


def render(config, integration_form, escape):
    # Host previews only; the ESP32 sends iter_render() without joining it.
    return b''.join(iter_render(config, integration_form, escape)).decode('utf-8')

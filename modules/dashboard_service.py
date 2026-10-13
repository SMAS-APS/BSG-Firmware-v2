"""Bounded application console and dashboard configuration/API services."""
import gc
import json
import time
from config_store import save
from station_clock import ClockService, DEFAULT_CLOCK, validate_clock


class DashboardService:
    def __init__(self, config, wlan, state):
        self.config, self.wlan, self.state = config, wlan, state
        self.radio = None
        settings = dict(DEFAULT_CLOCK)
        settings.update(config.get('clock', {}))
        config['clock'] = settings
        self.clock = ClockService(settings)
        self.lines = []
        self.scanning = False
        self.networks = []
        self.scan_message = 'Avvia la scansione'
        self.monitor_interval = int(config.get('runtime', {}).get('serial_interval_seconds', 10))
        self.last_status = {}
        self.log('Pannello pronto: AP e rete locale')
        self.log('Firmware %s · %s' % (state.get('firmware_version', ''), state.get('firmware_stage', '')))
        if state.get('error'):
            self.log('Errore ricevitore: ' + state['error'])

    def log(self, text):
        self.lines.append(str(text)[:1000])
        while len(self.lines) > 60 or sum(len(line) for line in self.lines) > 6000:
            del self.lines[0]

    def public_settings(self):
        fields = {
            'wifi': ('ssid', 'hidden'),
            'weather_underground': ('enabled', 'station_id', 'mode', 'upload_interval_seconds', 'utc_offset_minutes'),
            'amms': ('enabled', 'transport', 'auth_mode', 'station_id', 'key_id', 'url', 'timeout_seconds',
                     'upload_interval_seconds', 'mqtt_host', 'mqtt_port', 'mqtt_keepalive', 'mqtt_ca_cert'),
            'clock': tuple(DEFAULT_CLOCK),
            'runtime': ('poll_interval_ms', 'serial_interval_seconds'),
        }
        result = {section: {name: self.config.get(section, {}).get(name) for name in names}
                  for section, names in fields.items()}
        result['wifi']['has_password'] = bool(self.config.get('wifi', {}).get('password'))
        return result

    def scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.scan_message = 'Scansione in corso…'
        try:
            import _thread
            _thread.start_new_thread(self._scan_worker, ())
        except Exception:
            self.scanning = False
            self.scan_message = 'Impossibile avviare la scansione'

    def _scan_worker(self):
        try:
            self.wlan.active(True)
            if not self.wlan.isconnected():
                self.wlan.disconnect()
            names = {0: 'Aperta', 1: 'WEP', 2: 'WPA-PSK', 3: 'WPA2-PSK',
                     4: 'WPA/WPA2-PSK', 5: 'WPA2 Enterprise', 6: 'WPA3-PSK', 7: 'WPA2/WPA3'}
            found = []
            for ssid, bssid, channel, rssi, security, hidden in self.wlan.scan():
                found.append(dict(ssid=ssid.decode('utf-8', 'replace'), channel=channel,
                                  rssi=rssi, security=names.get(security, 'Protezione %s' % security), security_code=security,
                                  hidden=bool(hidden) or not ssid, bssid=':'.join('%02x' % b for b in bssid)))
            self.networks = sorted(found, key=lambda n: n['rssi'], reverse=True)
            self.scan_message = '%d reti rilevate' % len(self.networks)
        except Exception:
            self.scan_message = 'Scansione non riuscita; riprovare'
            self.networks = []
        finally:
            self.scanning = False

    def save_section(self, form, save_integrations):
        section = form.get('section')
        candidate = {key: value.copy() for key, value in self.config.items()}
        restart = False
        if section == 'wifi':
            wifi = candidate['wifi']
            ssid, password = form.get('ssid', ''), form.get('password', '')
            if not ssid or len(ssid.encode()) > 32 or len(password.encode()) > 64:
                raise ValueError('SSID o password Wi-Fi non validi')
            if form.get('clear_wifi_password') == 'on':
                password = ''
            elif not password and ssid == wifi.get('ssid'):
                password = wifi.get('password', '')
            wifi.update(ssid=ssid, password=password, hidden=form.get('network_hidden') == 'on')
            restart = True
        elif section == 'clock':
            clock = candidate['clock']
            for key in ('timezone', 'ntp_server'):
                clock[key] = form.get(key, clock[key]).strip()
            for key in ('utc_offset_minutes', 'sync_interval_seconds'):
                clock[key] = int(form.get(key, clock[key]))
            for key in ('ntp_enabled', 'dst_auto'):
                clock[key] = form.get(key) == 'on'
            validate_clock(clock)
        elif section == 'runtime':
            poll = int(form.get('poll_interval_ms', 25))
            serial = int(form.get('serial_interval_seconds', 10))
            if not 1 <= poll <= 100 or serial not in (0, 1, 5, 10, 30, 60):
                raise ValueError('Frequenze non valide')
            candidate['runtime'].update(poll_interval_ms=poll, serial_interval_seconds=serial)
        elif section == 'integrations':
            merged = dict(form)
            merged.update(ssid=candidate['wifi']['ssid'], password='')
            save_integrations(candidate, merged)
            self.config.update(candidate)
            self.state['restart_requested'] = time.ticks_ms()
            return dict(message='Servizi salvati. Riavvio in corso…', restart=True)
        else:
            raise ValueError('Sezione di configurazione non valida')
        save(candidate)
        self.config.update(candidate)
        self.clock.settings = candidate['clock']
        self.monitor_interval = candidate['runtime'].get('serial_interval_seconds', 10)
        if section == 'clock':
            self.clock.request_sync()
        if restart:
            self.state['restart_requested'] = time.ticks_ms()
        self.log('Configurazione %s salvata' % {'wifi': 'Wi-Fi', 'clock': 'orologio', 'runtime': 'frequenze'}.get(section, section))
        return dict(message='Configurazione salvata.' + (' Riavvio in corso…' if restart else ''), restart=restart)

    def command(self, command):
        command = command.strip()
        if len(command) > 160:
            raise ValueError('Comando troppo lungo')
        self.log('> ' + command)
        parts = command.lower().split()
        name = parts[0] if parts else 'help'
        if command.lower() in ('help', '?', ''):
            result = ('Comandi disponibili:\nhelp / ?          questo elenco\nstatus            stato della stazione\n'
                      'sensors           tutti i valori ricevuti\nstations          stazioni rilevate\nbattery           stato batteria RF per stazione (OK/LOW)\n'
                      'wifi              parametri di rete (senza password)\nwifi scan         scansione reti\n'
                      'radio             diagnostica ricevitore RF\nheap              memoria libera\n'
                      'uptime            tempo di funzionamento\ntime              data, fuso e NTP\n'
                      'ntp sync          sincronizza orologio\nserial 0|1|5|10|30|60  monitoraggio seriale e nel terminale (secondi)\n'
                      'monitor ...       alias di serial\nclear             pulisce registro del terminale\n'
                      'restart / reboot / reset  riavvia ESP\nexit              termina il comando')
        elif parts == ['battery']:
            result = json.dumps({key: dict(status='non disponibile' if value.get('battery_ok') is None else 'OK' if value['battery_ok'] else 'LOW', age_seconds=value.get('age_seconds')) for key, value in self.state.get('stations', {}).items()})
        elif name == 'status' and len(parts) == 1:
            result = json.dumps({k: self.state.get(k) for k in ('received', 'unrecognized', 'model', 'age_seconds', 'error', 'wifi_status', 'wu_status', 'amms_status')})
        elif name in ('sensors', 'stations', 'wifi', 'radio', 'time') and len(parts) == 1:
            key = {'sensors': 'sensors', 'stations': 'stations', 'wifi': 'network', 'radio': 'radio_diagnostics', 'time': 'clock'}[name]
            if name == 'radio' and self.radio and callable(getattr(self.radio, 'diagnostics', None)):
                self.state[key] = self.radio.diagnostics()
            result = json.dumps(self.state.get(key, {}))
        elif parts == ['wifi', 'scan']:
            self.scan()
            result = 'Scansione avviata; risultati nella pagina Wi-Fi'
        elif parts == ['ntp', 'sync']:
            if not self.clock.settings.get('ntp_enabled', True):
                raise ValueError('Abilitare NTP nella pagina Impostazioni')
            self.clock.request_sync()
            result = 'Sincronizzazione richiesta; serve una connessione Wi-Fi Internet'
        elif name == 'heap' and len(parts) == 1:
            result = str(gc.mem_free()) + ' byte liberi'
        elif name == 'uptime' and len(parts) == 1:
            result = str(self.state.get('uptime_seconds', 0)) + ' s'
        elif name in ('serial', 'monitor') and len(parts) == 2:
            value = int(parts[1])
            if value not in (0, 1, 5, 10, 30, 60):
                raise ValueError('Intervallo valido: 0, 1, 5, 10, 30, 60')
            self.monitor_interval = value
            result = 'Monitoraggio ogni %d s (temporaneo; Impostazioni per salvare)' % value
        elif parts == ['clear']:
            self.lines[:] = []
            result = 'Registro pulito'
        elif name in ('restart', 'reboot', 'reset') and len(parts) == 1:
            self.state['restart_requested'] = time.ticks_ms()
            result = 'Riavvio richiesto'
        elif parts == ['exit']:
            result = 'Pronto'
        else:
            raise ValueError('Comando non riconosciuto. Scrivi help.')
        self.log(result)
        return dict(message='Riavvio in corso…' if name in ('restart', 'reboot', 'reset') else '')

    def tick(self, now, connected):
        self.clock.tick(now, connected)
        self.state['clock'] = self.clock.snapshot()
        for name, value in [('NTP', self.clock.status), ('Wi-Fi', self.state.get('wifi_status')), ('AMMS', self.state.get('amms_status')), ('WU', self.state.get('wu_status'))]:
            if value != self.last_status.get(name):
                self.last_status[name] = value
                self.log('%s: %s' % (name, value))
        try:
            self.state['heap_free'] = gc.mem_free()
        except AttributeError:
            self.state['heap_free'] = None
        wifi = self.config.get('wifi', {})
        ap_active = self.state.get('ap_active', not connected)
        net = dict(mode=('AP + STA' if ap_active else 'STA') if connected else 'AP', ssid=wifi.get('ssid', ''),
                   ap_active=ap_active, ap_ssid=self.config['runtime'].get('ap_ssid', 'Bresser Gateway'),
                   ap_ip='192.168.4.1' if ap_active else None)
        if connected:
            try:
                ip, mask, gateway, dns = self.wlan.ifconfig()
                net.update(ip=ip, netmask=mask, gateway=gateway, dns=dns, rssi=self.wlan.status('rssi'))
            except Exception:
                pass
        try:
            import binascii
            net['mac'] = ':'.join('%02x' % b for b in self.wlan.config('mac'))
        except Exception:
            pass
        self.state['network'] = net

"""Nonblocking Wi-Fi recovery; leave the AP available while STA is unavailable."""
import time


class WifiRecovery:
    def __init__(self, config, wlan, ap, emit=print):
        self.config, self.wlan, self.ap, self.emit = config, wlan, ap, emit
        self.started = time.ticks_ms()
        self.last_attempt = None
        self.delay_ms = 30000
        self.force = False
        self.status = 'non configurato'
        self.last_report = None
        self.last_channel = None
        self.ap_enabled = bool(ap.active())

    def _set_ap(self, enabled):
        if self.ap_enabled == enabled:
            return
        self.ap.active(enabled)
        if enabled:
            self.ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '192.168.4.1'))
            self.ap.config(ssid=self.config.get('runtime', {}).get('ap_ssid', 'Bresser Gateway'),
                           security=0, channel=1, max_clients=4)
        self.ap_enabled = enabled
        self.last_channel = None
        self.emit('AP riattivato: http://192.168.4.1' if enabled else
                  'AP disattivato: connessione Wi-Fi al router attiva')

    def request_connect(self):
        self.force = True
        self.delay_ms = 30000

    def tick(self, now, scanning=False):
        wifi = self.config.get('wifi', {})
        try:
            connected = self.wlan.isconnected()
            self._set_ap(not connected or self.force)
            if self.ap_enabled:
                channel = self.ap.config('channel')
                if isinstance(channel, int) and channel != self.last_channel:
                    self.last_channel = channel
                    self.emit('AP: canale %d; AP e router condividono la radio' % channel)
            if connected and not self.force:
                self.status = 'connesso'
                self.delay_ms = 30000
            elif not wifi.get('ssid'):
                self.status = 'non configurato'
            else:
                code = self.wlan.status()
                messages = {-3: 'password rifiutata', -2: 'rete non trovata', -1: 'connessione non riuscita',
                            0: 'non connesso', 1: 'connessione in corso',
                            1000: 'non connesso', 1001: 'connessione in corso',
                            201: 'rete non trovata', 202: 'autenticazione rifiutata', 203: 'associazione non riuscita'}
                self.status = messages.get(code, 'errore collegamento (codice %s)' % code) if isinstance(code, int) else 'connessione in corso'
                due = self.last_attempt is None or time.ticks_diff(now, self.last_attempt) >= self.delay_ms
                ready = self.force or time.ticks_diff(now, self.started) >= 10000
                clients = self.ap.status('stations')
                has_clients = isinstance(clients, (list, tuple)) and bool(clients)
                # Automatic retries must not interrupt someone configuring the AP.
                if not scanning and ready and (self.force or (due and not has_clients and code not in (1, 1001))):
                    forced = self.force
                    self.force = False
                    self.last_attempt = now
                    self.wlan.active(True)
                    self.wlan.config(reconnects=0)
                    if forced:
                        self.wlan.disconnect()
                    self.wlan.connect(wifi['ssid'], wifi.get('password', ''))
                    self.status = 'connessione in corso'
                    self.emit('Wi-Fi: tentativo di connessione; AP disponibile. Esito riportato sulla seriale.')
                    self.delay_ms = min(300000, self.delay_ms * 2)
        except OSError as exc:
            try:
                self._set_ap(True)
            except OSError:
                self.emit('AP: riattivazione non riuscita; riprovo al prossimo ciclo')
            self.status = 'errore connessione'
            self.last_attempt = now
            self.force = False
            if self.last_report != self.status:
                self.emit('Wi-Fi: errore driver %s; AP mantenuto attivo' % str(exc))
        if self.status != self.last_report:
            self.last_report = self.status
            if self.status == 'connesso':
                self.emit('Wi-Fi connesso: http://%s | AP disattivato (ripristino automatico)' % self.wlan.ifconfig()[0])
            else:
                self.emit('Wi-Fi: ' + self.status)
        return self.status

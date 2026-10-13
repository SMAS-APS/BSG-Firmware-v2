"""Line-based serial commands with a password-masked Wi-Fi setup wizard."""
from config_store import save


class SerialCommands:
    def __init__(self, config, recovery, service, write=None):
        self.config, self.recovery, self.service = config, recovery, service
        self.write = write or self._write
        self.stage = 'command'
        self.buffer = bytearray()
        self.ssid = ''
        self.skip_lf = False
        self.echoed = 0
        self.overflow = False

    @staticmethod
    def _write(text):
        import sys
        sys.stdout.write(text)

    @property
    def configuring(self):
        return self.stage != 'command'

    def feed(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        for byte in data:
            if byte == 10 and self.skip_lf:
                self.skip_lf = False
                continue
            self.skip_lf = byte == 13
            if byte in (10, 13):
                self.write('\r\n')
                try:
                    value = self.buffer.decode('utf-8')
                    if self.overflow:
                        raise ValueError('Riga troppo lunga; ripetere config')
                    self._line(value)
                except (ValueError, UnicodeError, OSError, MemoryError):
                    # Never include input or filesystem exception text: it may contain a secret.
                    self.write('Configurazione o comando non riuscito. Dati precedenti conservati; ripetere config.\r\n')
                    self.stage = 'command'
                    self.ssid = ''
                self.buffer = bytearray()
                self.echoed = 0
                self.overflow = False
            elif byte in (8, 127):
                if self.buffer:
                    self.buffer.pop()
                    self.write('\b \b')
                    self.echoed = max(0, self.echoed - 1)
            elif byte >= 32:
                if len(self.buffer) >= 160:
                    self.overflow = True
                    continue
                self.buffer.append(byte)
                if self.stage == 'password':
                    self.write('*')
                else:
                    try:
                        text = self.buffer.decode('utf-8')
                        self.write(text[self.echoed:])
                        self.echoed = len(text)
                    except UnicodeError:
                        pass

    def _line(self, value):
        if self.stage == 'ssid':
            if not value or len(value.encode('utf-8')) > 32:
                raise ValueError('SSID non valido')
            self.ssid = value
            self.stage = 'password'
            self.write('Password Wi-Fi (Invio per rete aperta): ')
        elif self.stage == 'password':
            if len(value.encode('utf-8')) > 64:
                raise ValueError('Password troppo lunga')
            candidate = {key: section.copy() for key, section in self.config.items()}
            candidate['wifi'].update(ssid=self.ssid, password=value)
            save(candidate)
            self.config.update(candidate)
            self.stage = 'command'
            self.ssid = ''
            self.recovery.request_connect()
            try:
                self.service.log('Credenziali Wi-Fi salvate dalla seriale; connessione richiesta')
            except MemoryError:
                pass
            self.write('Configurazione salvata. Collegamento Wi-Fi richiesto, senza riavvio.\r\n')
        elif value.strip().lower() == 'config':
            self.stage = 'ssid'
            self.write('Configurazione Wi-Fi. Inserisci SSID (anche rete nascosta): ')
        elif value.strip():
            if value.strip().lower() in ('help', '?'):
                self.write('config: richiede SSID e password, salva e forza la connessione Wi-Fi.\r\n')
            self.service.command(value)
            if self.service.lines:
                self.write(self.service.lines[-1] + '\r\n')

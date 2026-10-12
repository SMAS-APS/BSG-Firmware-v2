"""Invii AMMS (HTTPS/MQTT) e WU in background, mantenendo attivi AP e RF."""
import time
from config_store import validate_weather_underground, validate_amms
from wu_support import canonical_sensor_values


class Uplink:
    def __init__(self, config, wlan):
        self.config = config
        self.wlan = wlan
        self.pending = None
        self.selected = None
        self.running = False
        self.status = "disabilitato"
        self.amms_status = "disabilitato"
        self.lock = None
        self.wu_enabled = config.get("weather_underground", {}).get("enabled", False)
        self.amms_enabled = config.get("amms", {}).get("enabled", False)
        if not self.wu_enabled and not self.amms_enabled:
            return
        try:
            validate_weather_underground(config)
            validate_amms(config)
            if not config.get("wifi", {}).get("ssid"):
                raise ValueError("configurare prima il Wi-Fi")
            import _thread
            self.lock = _thread.allocate_lock()
            self.running = True
            if self.wu_enabled:
                self.status = "in attesa di rete e dati"
            if self.amms_enabled:
                self.amms_status = "in attesa di rete e dati"
            _thread.start_new_thread(self._worker, ())
        except Exception:
            self.running = False
            if self.wu_enabled:
                self.status = "configurazione o avvio non riuscito"
            if self.amms_enabled:
                self.amms_status = "configurazione o avvio non riuscito"
            print("Invii remoti: configurazione o avvio non riuscito")

    def submit(self, reading):
        if not self.running:
            return
        # Una stazione remota corrisponde a un solo sensore: evita di mescolare ID.
        if reading.get("protocol") == "bresser_6in1" and reading.get("sensor_type") != 1:
            return
        if reading.get("protocol") == "bresser_7in1" and reading.get("sensor_type") not in (1, 12, 13):
            return
        if reading.get("protocol") == "bresser_5in1" and 0x39 <= reading.get("sensor_type", 0) <= 0x3B:
            return
        key = (reading.get("protocol"), reading.get("sensor_id"), reading.get("channel", 0))
        if self.selected is None:
            self.selected = key
            print("Stazione per gli invii remoti:", key)
        if key != self.selected:
            return
        with self.lock:
            self.pending = (reading.copy(), time.ticks_ms())

    def stop(self):
        self.running = False

    def _worker(self):
        client = None
        try:
            from main_app import _build_client, _build_weather_underground, _payload_from_reading
            import ntptime
            wu_client, tracker = _build_weather_underground(self.config)
            last_amms = None
            last_wu = None
            last_ntp = None
            latest = None
            rain = (None, None)
            while self.running:
                now = time.ticks_ms()
                if not self.wlan.isconnected():
                    if self.wu_enabled:
                        self.status = "in attesa del Wi-Fi"
                    if self.amms_enabled:
                        self.amms_status = "in attesa del Wi-Fi"
                    time.sleep_ms(500)
                    continue
                if last_ntp is None or time.ticks_diff(now, last_ntp) >= 3600000:
                    last_ntp = now
                    try:
                        ntptime.settime()
                        print("Orologio sincronizzato via NTP")
                    except Exception:
                        last_ntp = time.ticks_add(now, -3540000)
                if time.gmtime()[0] < 2024:
                    if self.wu_enabled:
                        self.status = "in attesa sincronizzazione NTP"
                    if self.amms_enabled:
                        self.amms_status = "in attesa sincronizzazione NTP"
                    time.sleep_ms(500)
                    continue
                with self.lock:
                    pending = self.pending
                    self.pending = None
                if pending:
                    latest = pending
                    if tracker:
                        rain = tracker.update(pending[0], int(time.time()))
                if latest is None or time.ticks_diff(now, latest[1]) > 120000:
                    time.sleep_ms(250)
                    continue
                reading = latest[0]
                epoch = int(time.time())
                if self.amms_enabled and (last_amms is None or time.ticks_diff(now, last_amms) >= int(self.config["amms"].get("upload_interval_seconds", 10)) * 1000):
                    last_amms = now
                    try:
                        if client is None:
                            client, transport = _build_client(self.config["amms"])
                        result = client.send(_payload_from_reading(reading), clear_on_success=False)
                        self.amms_status = "dati pubblicati via " + transport if result.ok else "invio rifiutato"
                    except Exception:
                        self.amms_status = "errore connessione AMMS"
                    print("AMMS:", self.amms_status)
                if wu_client and (last_wu is None or time.ticks_diff(now, last_wu) >= wu_client.upload_interval_seconds * 1000):
                    last_wu = now
                    try:
                        result = wu_client.send({"sensors": canonical_sensor_values(reading)}, epoch,
                            hourly_rain_mm=rain[0], daily_rain_mm=rain[1])
                        self.status = "dati pubblicati" if result.ok else "invio rifiutato da WU"
                    except Exception:
                        self.status = "errore connessione HTTPS WU"
                    print("Weather Underground:", self.status)
                time.sleep_ms(250)
        except Exception:
            if self.wu_enabled:
                self.status = "errore servizio invii"
            if self.amms_enabled:
                self.amms_status = "errore servizio invii"
            print("Errore servizio invii remoti")
        finally:
            self.running = False
            if client:
                try:
                    client.close()
                except Exception:
                    pass

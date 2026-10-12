"""UTC RTC, configurable NTP and automatic European daylight saving time."""
import time

ZONES = {"Europe/Rome": 60, "Europe/Paris": 60, "Europe/Berlin": 60,
         "Europe/Madrid": 60, "Europe/London": 0, "Europe/Athens": 120, "UTC": 0}
DEFAULT_CLOCK = dict(ntp_enabled=True, ntp_server="pool.ntp.org", timezone="Europe/Rome",
                     utc_offset_minutes=60, dst_auto=True, sync_interval_seconds=3600)


def validate_clock(settings):
    if settings.get("timezone") not in ZONES and settings.get("timezone") != "Custom":
        raise ValueError("Fuso orario non supportato")
    host = settings.get("ntp_server", "")
    if not host or len(host) > 253 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in host):
        raise ValueError("Server NTP non valido")
    if not -720 <= int(settings.get("utc_offset_minutes", 60)) <= 840:
        raise ValueError("Scostamento UTC non valido")
    if not 60 <= int(settings.get("sync_interval_seconds", 3600)) <= 86400:
        raise ValueError("Intervallo NTP non valido")


def offset_minutes(settings, epoch=None):
    epoch = time.time() if epoch is None else epoch
    zone = settings.get("timezone", "Europe/Rome")
    base = ZONES.get(zone, int(settings.get("utc_offset_minutes", 60)))
    dst = False
    if settings.get("dst_auto", True) and zone.startswith("Europe/"):
        year, month, day, hour = time.gmtime(epoch)[:4]
        if 3 < month < 10:
            dst = True
        elif month in (3, 10):
            # gmtime weekday: Monday=0; transition at 01:00 UTC.
            # Gregorian weekday, Sunday=0; independent of host local timezone.
            table = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
            y = year - (1 if month < 3 else 0)
            weekday = (y + y // 4 - y // 100 + y // 400 + table[month - 1] + 31) % 7
            sunday = 31 - weekday
            after = day > sunday or (day == sunday and hour >= 1)
            dst = after if month == 3 else not after
    return base + (60 if dst else 0), dst


def clock_status(settings):
    valid = time.gmtime()[0] >= 2024
    offset, dst = offset_minutes(settings)
    parts = time.gmtime(time.time() + offset * 60)
    return dict(valid=valid, local_time="%02d/%02d/%04d %02d:%02d:%02d" %
                (parts[2], parts[1], parts[0], parts[3], parts[4], parts[5]) if valid else "Non sincronizzato",
                timezone=settings.get("timezone", "Europe/Rome"), utc_offset_minutes=offset, dst=dst)


class ClockService:
    def __init__(self, settings):
        self.settings = settings
        self.busy = False
        self.last_attempt = None
        self.last_sync = None
        self.status = "in attesa di rete"
        self.force = False

    def request_sync(self):
        self.force = True

    def tick(self, now, connected):
        if self.busy or not connected or not self.settings.get("ntp_enabled", True):
            return
        interval = int(self.settings.get("sync_interval_seconds", 3600)) * 1000 if self.status == "sincronizzato" else 60000
        if not self.force and self.last_attempt is not None and time.ticks_diff(now, self.last_attempt) < interval:
            return
        self.force = False
        self.last_attempt = now
        self.busy = True
        try:
            import _thread
            _thread.start_new_thread(self._sync, ())
        except Exception:
            self.busy = False
            self.status = "avvio NTP non riuscito"

    def _sync(self):
        try:
            import ntptime
            ntptime.host = self.settings.get("ntp_server", "pool.ntp.org")
            ntptime.timeout = 3
            ntptime.settime()
            self.last_sync = time.time()
            self.status = "sincronizzato"
        except Exception:
            self.status = "sincronizzazione non riuscita; nuovo tentativo tra 60 s"
        finally:
            self.busy = False

    def snapshot(self):
        result = clock_status(self.settings)
        result.update(status=self.status if self.settings.get("ntp_enabled", True) else "NTP disabilitato",
                      syncing=self.busy, last_sync=self.last_sync)
        return result

"""Impulso sul LED utente senza fermare radio, DNS o HTTP."""
import time


class ReceiveLED:
    def __init__(self, config):
        from machine import Pin
        self.active = 0 if config.get("led_active_low", False) else 1
        self.duration = max(20, min(1000, int(config.get("led_pulse_ms", 100))))
        self.pin = Pin(int(config.get("led_pin", 2)), Pin.OUT, value=1 - self.active)
        self.started = None

    def pulse(self, now):
        self.pin.value(self.active)
        self.started = now

    def tick(self, now):
        if self.started is not None and time.ticks_diff(now, self.started) >= self.duration:
            self.off()

    def off(self):
        self.pin.value(1 - self.active)
        self.started = None

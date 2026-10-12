"""mpremote con recupero della sincronizzazione REPL durante l'avvio CP210x."""
import sys
import time
from mpremote.transport import TransportError
from mpremote.transport_serial import SerialTransport
from mpremote.main import main

original_enter_raw_repl = SerialTransport.enter_raw_repl


def enter_raw_repl_ready(self, soft_reset=True):
    for attempt in range(3):
        try:
            return original_enter_raw_repl(self, soft_reset=soft_reset)
        except TransportError as exc:
            if "could not enter raw repl" not in str(exc) or attempt == 2:
                raise
            # Riprova solo l'handshake, prima di eseguire codice o copie file.
            # Mantiene aperta la porta: riaprirla potrebbe causare un altro reset.
            print("Scheda ancora in avvio: riprovo la connessione al REPL...", flush=True)
            time.sleep(1)
            self.serial.write(b"\r\x03\x03\x02")
            time.sleep(0.2)


if __name__ == "__main__":
    SerialTransport.enter_raw_repl = enter_raw_repl_ready
    sys.exit(main())

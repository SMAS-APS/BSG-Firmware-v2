"""Monitor seriale: apre prima la porta e poi riavvia Python per catturare l'avvio."""
import argparse
import sys
import time


def restart_python(port, timeout_seconds=8):
    # Interrompe l'app e lascia raw REPL, se necessario. Ctrl-D in friendly
    # REPL riavvia boot.py/main.py senza cancellare configurazione o filesystem.
    port.write(b"\r\x03\x03\x02")
    deadline = time.monotonic() + timeout_seconds
    received = bytearray()
    retry = time.monotonic() + 1
    while time.monotonic() < deadline:
        received.extend(port.read(max(1, port.in_waiting)))
        if b">>>" in received:
            port.write(b"\x04")
            return
        if time.monotonic() >= retry:
            port.write(b"\r\x03\x03\x02")
            retry = time.monotonic() + 1
    raise RuntimeError("La scheda non risponde al REPL. Premere EN/RESET o controllare la porta. "
                       + bytes(received[-512:]).decode("utf-8", "replace"))


def monitor(device, restart=True):
    import serial
    from mpremote.console import Console
    # Configura DTR/RTS prima di aprire: evita reset indesiderati con CP210x.
    port = serial.Serial(port=None, baudrate=115200, timeout=0.1)
    port.dtr = False
    port.rts = False
    port.port = device
    console = None
    try:
        port.open()
        print("Connesso a %s, 115200 baud. Ctrl-C: ferma app; Ctrl-D: riavvia; Ctrl-]: esci." % device, flush=True)
        if restart:
            print("Riavvio Python dopo la connessione: versione e avvio saranno visibili.", flush=True)
            restart_python(port)
        console = Console()
        console.enter()
        while True:
            console.waitchar(port)
            char = console.readchar()
            if char in (b"\x1d", b"\x18"):
                return
            if char:
                port.write(char)
            if port.in_waiting:
                sys.stdout.buffer.write(port.read(port.in_waiting))
                sys.stdout.buffer.flush()
    finally:
        if console:
            console.exit()
        port.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--no-restart", action="store_true", help="Lascia l'app in esecuzione e osserva i prossimi messaggi")
    args = parser.parse_args()
    try:
        monitor(args.port, not args.no_restart)
    except (OSError, RuntimeError) as exc:
        print("Errore monitor:", exc, file=sys.stderr)
        sys.exit(1)

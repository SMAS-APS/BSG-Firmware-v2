"""Menu e comandi per flashare MicroPython+Bresser e aggiornare i file Python."""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import runpy
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
DEFAULT_IMAGE = PROJECT / ".pio/build/esp32-wroom-32/firmware.bin"
VERIFY_CODE = (
    "import sys, bresser_native, bsg_runtime; "
    "assert bsg_runtime.FIRMWARE_SCHEMA >= 2, 'Aggiornare il firmware BSG'; "
    "print('MicroPython:', sys.version); "
    "print('Firmware BSG:', getattr(bsg_runtime, 'FIRMWARE_VERSION', 'precedente a 0.1.0'), "
    "getattr(bsg_runtime, 'FIRMWARE_STAGE', 'non indicata')); "
    "print('Libreria Bresser presente; avvio Python aggiornabile OK')"
)
DEPLOY_VERIFY_CODE = (VERIFY_CODE + "; assert callable(getattr(bresser_native, 'poll_raw', None)), 'Prima ricompilare e flashare BSG: manca API RF 6/7-in-1'; "
                     "assert getattr(bresser_native, 'RF_DRIVER_REVISION', 0) >= 2, 'Prima ricompilare e flashare BSG: serve il driver RF corretto (revisione 2)'")


def require(*modules):
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("Mancano gli strumenti %s. Eseguire: %s -m pip install -r requirements-tools.txt" % (
            ", ".join(missing), sys.executable))


def run(arguments):
    return subprocess.run([str(value) for value in arguments], check=True)


def list_ports():
    require("serial")
    from serial.tools import list_ports as serial_ports
    ports = sorted(serial_ports.comports(), key=lambda value: value.device)
    for index, port in enumerate(ports, 1):
        print("%d. %s - %s" % (index, port.device, port.description))
    if not ports:
        print("Nessuna porta seriale: collegare la scheda con un cavo USB dati e controllare il driver.")
    return ports


def choose_port():
    ports = list_ports()
    if not ports:
        raise RuntimeError("Scheda non trovata")
    index = int(input("Numero della porta della scheda: ")) - 1
    if not 0 <= index < len(ports):
        raise RuntimeError("Porta non valida")
    return ports[index].device


def validate_image(image):
    image = Path(image).resolve()
    if not image.is_file():
        raise RuntimeError("Immagine non trovata. Eseguire prima python build_firmware.py build.")
    metadata_file = image.with_suffix(".bin.json")
    if not metadata_file.is_file():
        raise RuntimeError("Manca il file .bin.json dell'immagine BSG. Ricompilare con build_firmware.py build.")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise RuntimeError("Metadati dell'immagine non validi: ricompilare il firmware.")
    if metadata.get("chip") != "esp32" or metadata.get("flash_offset") != 4096:
        raise RuntimeError("Immagine non destinata a ESP32-WROOM-32")
    if metadata.get("schema") != 2 or "bresser_native" not in metadata.get("native_modules", []):
        raise RuntimeError("Serve l'immagine MicroPython BSG con libreria Bresser e avvio aggiornabile.")
    if metadata.get("native_api", 1) < 2:
        raise RuntimeError("Immagine precedente all'autoriconoscimento 6/7-in-1: ricompilare con build_firmware.py build.")
    if metadata.get("rf_driver_revision", 0) < 2:
        raise RuntimeError("Immagine con driver RF precedente: ricompilare per includere la correzione della ricezione.")
    if hashlib.sha256(image.read_bytes()).hexdigest() != metadata.get("sha256"):
        raise RuntimeError("L'immagine non corrisponde al suo SHA256: ricompilare o recuperare la coppia .bin/.bin.json originale.")
    return image


def python_files():
    if not (PROJECT / "external/AMMSUtils/amms/__init__.py").is_file():
        raise RuntimeError("AMMSUtils mancante: git submodule update --init --recursive")
    files = [(PROJECT / "boot.py", "/boot.py"), (PROJECT / "main.py", "/main.py")]
    files += [(path, "/" + path.name) for path in sorted((PROJECT / "modules").glob("*.py"))]
    library = PROJECT / "external/AMMSUtils"
    files += [(path, "/lib/" + path.relative_to(library).as_posix())
              for path in sorted((library / "amms").rglob("*.py"))]
    for path, _ in files:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    return files


def deploy(port):
    require("mpremote")
    files = python_files()
    dirs = {str(Path(remote).parent).replace("\\", "/") for _, remote in files}
    dirs.add("/lib")
    dirs.discard("/")
    mkdir_code = "import os\nfor path in %r:\n try:\n  os.mkdir(path)\n except OSError as e:\n  if e.args[0] != 17: raise\n" % (
        tuple(sorted(dirs, key=lambda value: (value.count("/"), value))),)
    command = [sys.executable, PROJECT / "mpremote_bridge.py", "connect", port, "soft-reset",
               "exec", DEPLOY_VERIFY_CODE, "+", "exec", mkdir_code, "+"]
    for local, remote in files:
        # LittleFS sostituisce atomicamente ogni file dopo una copia completa.
        temporary = remote + ".bsg-tmp"
        command += ["fs", "cp", local, ":" + temporary, "+", "exec",
                    "import os; os.rename(%r, %r)" % (temporary, remote), "+"]
    command += ["exec", "--no-follow", "import machine; machine.reset()"]
    run(command)
    print("File Python aggiornati e scheda riavviata. Configurazione e credenziali conservate.")


def flash(port, image=DEFAULT_IMAGE, erase=False):
    require("esptool", "mpremote")
    image = validate_image(image)
    python_files()  # Controllare tutte le sorgenti prima di modificare la scheda.
    base = [sys.executable, "-m", "esptool", "--chip", "esp32", "--port", port]
    if erase:
        print("Cancellazione di tutta la flash, inclusi configurazione e dati salvati.")
        run(base + ["erase_flash"])
    run(base + ["--baud", "460800", "write_flash", "-z", "--flash_mode", "dio",
                "--flash_freq", "40m", "--flash_size", "detect", "0x1000", image])
    deploy(port)


def check(port):
    require("mpremote")
    # La verifica interrompe l'applicazione; riavviamo la scheda al termine.
    run([sys.executable, PROJECT / "mpremote_bridge.py", "connect", port, "soft-reset", "exec",
         VERIFY_CODE, "+", "exec", "--no-follow", "import machine; machine.reset()"])


def monitor(port):
    require("mpremote", "serial")
    run([sys.executable, PROJECT / "serial_monitor.py", "--port", port])


def menu():
    version = runpy.run_path(str(PROJECT / "modules/bsg_runtime.py"))["FIRMWARE_VERSION"]
    print("Bresser Gateway %s - MicroPython / ESP32-WROOM-32" % version)
    while True:
        print("\n1 Porte USB\n2 Installa MicroPython+Bresser (immagine gia compilata)\n"
              "3 Aggiorna solo i file Python\n4 Monitor seriale\n5 Verifica MicroPython\n"
              "6 Compila l'immagine con ESP-IDF\n7 Installa gli strumenti USB\n0 Esci")
        action = input("Scelta: ").strip()
        if action == "0":
            return
        try:
            if action == "1":
                list_ports()
            elif action == "6":
                run([sys.executable, PROJECT / "build_firmware.py", "build"])
            elif action == "7":
                run([sys.executable, "-m", "pip", "install", "-r", PROJECT / "requirements-tools.txt"])
            elif action in ("2", "3", "4", "5"):
                port = choose_port()
                if action == "2":
                    erase = input("Prima installazione? Scrivere CANCELLA per svuotare tutta la flash, altrimenti Invio: ") == "CANCELLA"
                    flash(port, erase=erase)
                elif action == "3":
                    deploy(port)
                elif action == "4":
                    monitor(port)
                else:
                    check(port)
        except (RuntimeError, ValueError, SyntaxError, OSError, subprocess.CalledProcessError) as error:
            print("Operazione non riuscita:", error)
            print("Consultare GUIDA_FLASH.md. Chiudere gli altri monitor seriali e verificare cavo/porta.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["ports", "flash", "deploy", "monitor", "check"])
    parser.add_argument("--port", help="Porta della scheda, per esempio COM5")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--erase", action="store_true", help="Cancella configurazione e tutti i dati prima del flash")
    args = parser.parse_args(argv)
    if not args.action:
        menu()
    elif args.action == "ports":
        list_ports()
    else:
        if not args.port:
            parser.error("Specificare --port COM5 (o la porta effettiva)")
        if args.erase and args.action != "flash":
            parser.error("--erase e valido solo con flash")
        if args.action == "flash":
            flash(args.port, args.image, args.erase)
        else:
            {"deploy": deploy, "monitor": monitor, "check": check}[args.action](args.port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperazione interrotta.")
        sys.exit(130)
    except (RuntimeError, ValueError, SyntaxError, OSError, subprocess.CalledProcessError) as error:
        print("Errore:", error, file=sys.stderr)
        sys.exit(1)

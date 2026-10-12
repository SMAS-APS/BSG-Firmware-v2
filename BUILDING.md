# Compilazione locale ESP-IDF / MicroPython

La procedura completa, inclusi installazione e uso da JetBrains, Eclipse,
VS Code e terminale, e in fondo al [README](README.md#installazione-completa-e-uso-da-qualsiasi-ide).

Dalla cartella che contiene `build_firmware.py`:

```sh
python build_firmware.py doctor
python build_firmware.py prepare
python build_firmware.py build
python build_firmware.py flash --port COM5
python build_firmware.py monitor --port COM5
```

Richiede ESP-IDF v5.5.2 installato localmente, MicroPython v1.29.0 e i pacchetti
`requirements-build.txt` installati nel Python ESP-IDF. Nessun Docker o WSL.
PlatformIO e opzionale e richiama la stessa build locale.
Il driver RFM95W/SX1276 e il decoder Bresser restano in C++ nativo;
applicazione, seriale e captive portal restano in MicroPython.
I sorgenti MicroPython vanno nella cache utente esterna; la build e in `.pio/`.
Il risultato e `.pio/build/esp32-wroom-32/firmware.bin`.

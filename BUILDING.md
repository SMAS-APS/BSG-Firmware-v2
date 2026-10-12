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

## Flash e sviluppo Python semplificati

Aprire [GUIDA_FLASH.md](GUIDA_FLASH.md) o avviare `bsg.cmd` su Windows.
Dopo la build, l'immagine e accompagnata da `firmware.bin.json` (SHA256,
scheda e modulo nativo). Con la coppia gia compilata non serve ESP-IDF per
installare la scheda: bastano `requirements-tools.txt` e `bsg.py flash`.

```sh
python bsg.py ports
python bsg.py flash --port COM5
python bsg.py deploy --port COM5
python bsg.py monitor --port COM5
```

`flash` installa MicroPython+Bresser e copia anche gli script aggiornati.
`deploy` aggiorna solo i file Python e riavvia la scheda, conservando i dati.
Il C++ della radio resta incluso nell'interprete. I moduli congelati restano
come ripiego; il nuovo avvio usa quelli nel filesystem quando presenti.

La nuova API nativa `poll_raw` abilita le estensioni 6/7-in-1 in Python.
Dopo questo aggiornamento compilare e flashare una volta l'immagine; il
caricatore rifiuta il solo deploy su immagini prive della nuova API.
`firmware.bin.json` include `native_api: 2`. Il cablaggio aggiornato e nel
README: RESET32, DIO0 21 e DIO1 33. Gli strumenti di build impostano UTF-8
anche su Windows per congelare correttamente i testi del portale.

# BSG Gateway

Il repository contiene due implementazioni separate del gateway per stazioni meteo Bresser 5-in-1:

- [`esp32/`](esp32/README.md): firmware MicroPython con ricevitore SX1276/RFM95W nativo in C++;
- [`raspberry-pi3/`](raspberry-pi3/README.md): servizio Python per Raspberry Pi 3 e Raspberry Pi OS.

Entrambe leggono lo stesso protocollo radio e inviano ad AMMS lo stesso payload JSON. Il codice hardware non è condiviso: ESP32 usa ESP-IDF, mentre Raspberry Pi usa le interfacce Linux SPI e GPIO.

Il client AMMS comune proviene dal submodule [`external/AMMSUtils`](external/AMMSUtils), fissato a una versione verificata. Dopo il clone inizializzarlo con:

```sh
git submodule update --init --recursive
```

## Quale versione usare

| Piattaforma | Runtime | Installazione | Riavvio dopo crash |
|---|---|---|---|
| ESP32 | MicroPython + modulo C++ | compilazione firmware personalizzato | riavvio della scheda |
| Raspberry Pi 3 | Python 3 su Raspberry Pi OS | `sudo bash install.sh` | automatico tramite `systemd` |

Per le due stazioni basate su Raspberry Pi 3, seguire la guida in [`raspberry-pi3/README.md`](raspberry-pi3/README.md). Ogni Raspberry deve avere il proprio `/etc/bsg-gateway/config.json` con il token AMMS corretto.

Non inserire token reali nei file versionati.

# Gateway per Raspberry Pi 3

Questa versione usa Python 3 su Raspberry Pi OS. Legge il ricevitore SX1276/RFM95W tramite SPI, decodifica i messaggi Bresser 5-in-1 e invia i dati ad AMMS tramite HTTPS.

Non usa MicroPython: il Wi-Fi e l'orologio sono gestiti direttamente da Raspberry Pi OS. Il servizio `systemd` parte al boot e, se il processo Python termina per un errore, lo riavvia dopo 5 secondi senza un limite massimo di tentativi.

## Collegamenti RFM95W

I numeri GPIO sono in formato BCM.

| RFM95W | Raspberry Pi 3 | Pin fisico |
|---|---:|---:|
| 3.3V | 3.3V | 1 oppure 17 |
| GND | GND | 6, 9, 14, 20, 25, 30, 34 o 39 |
| SCK | GPIO11 / SPI0 SCLK | 23 |
| MOSI | GPIO10 / SPI0 MOSI | 19 |
| MISO | GPIO9 / SPI0 MISO | 21 |
| NSS / CS | GPIO8 / SPI0 CE0 | 24 |
| RESET | GPIO25 | 22 |
| DIO0 | GPIO24 | 18 |
| DIO1 | non collegato | - |

Il modulo deve essere alimentato esclusivamente a 3,3 V. Collegarlo a 5 V può danneggiarlo.

## Installazione rapida

Configurare prima il Raspberry Pi sulla rete Wi-Fi desiderata, quindi clonare l'intero repository con la dipendenza AMMSUtils:

```sh
git clone --recurse-submodules https://github.com/SMAS-APS/BSG-Firmware-v2.git
cd BSG-Firmware-v2
```

Se il repository è stato clonato senza dipendenze, dalla sua radice eseguire prima:

```sh
git submodule update --init --recursive
```

Poi installare:

```sh
cd raspberry-pi3
sudo bash install.sh
```

Alla prima installazione vengono generati automaticamente `station_id`, `key_id` e
una chiave HMAC-SHA256 da 256 bit. Le credenziali non vengono rigenerate durante gli
aggiornamenti.

Se il server espone l'endpoint di registrazione, e' possibile completare tutto in un
solo passaggio. Il codice monouso non deve essere scritto nella riga di comando:

```sh
sudo AMMS_ENROLL_CODE='CODICE_MONOUSO' bash install.sh \
  --enroll-url 'https://weather.iacca.ml/api/stations/enroll'
```

Senza `--enroll-url`, lo script crea il file protetto
`/etc/bsg-gateway/enrollment.json` e lascia il servizio fermo. Importare quel file
nel server, eliminarlo dal Raspberry e avviare il servizio:

```sh
sudo rm /etc/bsg-gateway/enrollment.json
sudo systemctl start bsg-gateway.service
```

Finche' il file di registrazione esiste, anche l'avvio automatico al boot resta
bloccato dalla condizione configurata nell'unita' `systemd`.

Il server deve accettare il documento JSON soltanto previa verifica di un codice
monouso e rispondere con uno stato HTTP `2xx`. La trasmissione avviene esclusivamente
tramite HTTPS con verifica del certificato.

Per ruotare la chiave mantenendo l'identificativo della stazione:

```sh
sudo AMMS_ENROLL_CODE='NUOVO_CODICE' bash install.sh --rotate-key \
  --enroll-url 'https://weather.iacca.ml/api/stations/enroll'
```

Durante la migrazione e' ancora possibile installare con il vecchio token Bearer:

```sh
sudo bash install.sh --token 'TOKEN_AMMS'
```

Lo script:

1. installa Python, `spidev`, `gpiozero` e i certificati TLS;
2. abilita SPI;
3. crea l'utente limitato `bsg-gateway`;
4. installa l'applicazione in `/opt/bsg-gateway`;
5. genera e salva le credenziali in `/etc/bsg-gateway/config.json`;
6. abilita e avvia `bsg-gateway.service`.

Se SPI diventa disponibile soltanto dopo il riavvio, l'installer lo segnala. In quel caso basta eseguire:

```sh
sudo reboot
```

## Gestione del servizio

```sh
systemctl status bsg-gateway.service
journalctl -u bsg-gateway.service -f
sudo systemctl restart bsg-gateway.service
```

Il riavvio automatico è configurato in `bsg-gateway.service` con `Restart=on-failure`, `RestartSec=5` e senza limite di tentativi.

## Configurazione

Per modificare credenziali, URL, frequenza o pin:

```sh
sudoedit /etc/bsg-gateway/config.json
sudo systemctl restart bsg-gateway.service
```

Per due stazioni eseguire l'installazione separatamente sui due Raspberry Pi: ogni
dispositivo ricevera' una chiave differente. Il file di configurazione ha permessi
limitati e non viene sovrascritto quando si rilancia l'installer.

## Test senza radio

Il decoder può essere verificato anche su un normale computer con Python 3:

```sh
python3 -m unittest discover -s tests -v
```

La parte SPI/GPIO richiede invece il Raspberry Pi e il modulo radio collegato.

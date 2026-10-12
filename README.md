# BSG Firmware v2 - MicroPython + ricevitore nativo

Questo repository contiene il firmware ESP32 del gateway Bresser con:

- logica applicativa in MicroPython;
- configurazione Wi-Fi tramite pagina Web locale;
- upload opzionale Weather Underground PWS o RapidFire;
- invio MQTT/TLS con payload JSON compatto e QoS 1;
- HTTPS firmato HMAC-SHA256 disponibile come fallback;
- ricevitore RFM95W/SX1276 e decoder Bresser 5-in-1 in C++ nativo;
- test del decoder eseguibili anche senza scheda ESP32.

## Stato del progetto

Il decoder Bresser 5-in-1 e l'interfaccia MicroPython sono implementati. Il driver nativo configura direttamente l'SX1276 in FSK a 868,3 MHz usando ESP-IDF, senza richiedere Arduino Core o RadioLib.

La parte radio deve essere validata sulla scheda reale, perché in questo ambiente non è collegato un ESP32 con RFM95W. Prima di sostituire un gateway operativo, confrontare per almeno alcune ore i valori ricevuti dal firmware precedente e da questo firmware.

## Hardware previsto

La configurazione predefinita e la build sono destinate alla **BSG Board v2**
basata su ESP32-S3. Il ricevitore usa `SPI2_HOST` (`spi_host=1`) e il pinout
seguente:

| RFM95W | ESP32-S3 |
|---|---:|
| RESET | GPIO14 |
| NSS / CS | GPIO10 |
| SCK | GPIO12 |
| MOSI | GPIO11 |
| MISO | GPIO13 |
| DIO0 | GPIO6 |
| DIO1 | GPIO7, non utilizzato dal firmware corrente |
| DIO2 | GPIO4, non utilizzato dal firmware corrente |
| 3.3V | 3.3V |
| GND | GND |

Gli altri collegamenti predisposti sulla scheda, non ancora inizializzati da
questo firmware, sono:

| Blocco | Collegamenti ESP32-S3 |
|---|---|
| Display CN3 | CS GPIO42, RST GPIO38, DC GPIO2, MOSI GPIO40, SCK GPIO39, BL GPIO47, MISO GPIO48 |
| LED RGB | GPIO17 |
| NTC 100K | GPIO1 |
| SPS30 CN2 | SCL GPIO9, SDA GPIO8 |
| SD | MOSI GPIO21, MISO GPIO48, CS GPIO15, SCK GPIO16 |
| Espansione | IO1 GPIO5, IO2 GPIO18, IO3 GPIO3, IO4 GPIO46, IO5 GPIO43, IO6 GPIO44 |

## Struttura

```text
BSG-Firmware-v2/
|-- boot.py
|-- main.py
|-- manifest.py
|-- config.example.json
|-- modules/
|   |-- config_store.py
|   |-- main_app.py
|   |-- mqtt_transport.py
|   |-- wifi_manager.py
|   `-- wu_support.py
|-- native/
|   |-- micropython.cmake
|   `-- bresser_native/
|       |-- bresser_decoder.cpp/.hpp
|       |-- sx1276_receiver.cpp/.hpp
|       |-- modbresser_native.cpp
|       `-- micropython.cmake
|-- tests/
|   |-- CMakeLists.txt
|   |-- test_config_store.py
|   |-- test_decoder.cpp
|   |-- test_embedded_amms.py
|   `-- test_wu_support.py
|-- external/
|   `-- AMMSUtils/
`-- BUILDING.md
```

Il client AMMS, il codec MQTT e il trasporto HTTPS sono forniti dal submodule `external/AMMSUtils` e vengono congelati nel firmware dal manifest. `umqtt.simple` viene incluso durante la compilazione.

## API del modulo nativo

```python
import bresser_native

bresser_native.init(
    spi_host=1,
    sck=12,
    mosi=11,
    miso=13,
    cs=10,
    reset=14,
    dio0=6,
    frequency_hz=868_300_000,
)

reading = bresser_native.poll()
if reading:
    print(reading)
```

`poll()` non blocca: restituisce `None` quando non è pronto un pacchetto valido. Quando riceve un messaggio 5-in-1 valido restituisce un dizionario con temperatura, umidità, vento, pioggia, batteria, RSSI e payload grezzo.

Sono inoltre disponibili:

- `bresser_native.decode(payload)` per provare un payload di 26 byte senza radio;
- `bresser_native.stats()` per contatori e diagnostica;
- `bresser_native.status()` per configurazione e versione del chip;
- `bresser_native.sleep()`, `wake()` e `deinit()`.

## Avvio rapido

1. Compilare il firmware seguendo [BUILDING.md](BUILDING.md).
2. Installarlo sull'ESP32.
3. Registrare la stazione sul server e ottenere `station_id`, `key_id`, `secret_hex` e i parametri MQTT.
4. Scaricare `https://HOST-AMMS/api/mqtt/ca.crt` e copiarlo sulla scheda come `/mqtt-ca.crt`; in alternativa incollare il PEM nel portale locale.
5. Copiare `config.example.json` sulla scheda come `/config.json` e inserire le credenziali, oppure lasciare che il dispositivo apra la rete `Bresser Gateway`.
6. Collegarsi alla rete temporanea e aprire `http://192.168.4.1`.
7. Inserire Wi-Fi, credenziali, host MQTT e CA.

## Weather Underground

La sezione `weather_underground` e' disabilitata per impostazione predefinita.
Quando abilitata richiede station ID, station key, modalita' `rapidfire` o
`standard`, intervallo minimo di 10 secondi e offset UTC locale in minuti.
L'offset va aggiornato manualmente al cambio dell'ora legale.

Il contatore cumulativo Bresser viene trasformato in pioggia oraria e
giornaliera e salvato atomicamente in `/wu-rain-state.json`. Dopo una prima
installazione o uno stato non valido i campi pioggia vengono omessi finche' non
esiste una finestra temporale affidabile; temperatura, umidita' e vento
continuano a essere pubblicati. Gli errori WU non interrompono gli invii AMMS.

Le velocita' Bresser, ricevute in m/s, vengono normalizzate in km/h prima di
essere inviate sia ad AMMS sia a Weather Underground.

Il certificato del broker viene verificato contro la CA configurata e il nome
host deve corrispondere al certificato. Ogni stazione puo' pubblicare soltanto
sui propri topic `amms/v1/stations/<station_id>/telemetry` e `status`.

Non inserire token o chiavi reali nei file versionati. Il token Bearer e' ancora
supportato selezionando `bearer`, esclusivamente per la migrazione di installazioni
esistenti.

La rete di configurazione locale di questa prima versione non e' cifrata. Per una
stazione di produzione e' quindi preferibile copiare `/config.json` tramite collegamento
USB/seriale; usare la pagina Web soltanto in un ambiente fisicamente controllato.

## Limiti iniziali

- È implementato il protocollo Bresser 5-in-1 usato dal firmware attuale.
- 6-in-1, 7-in-1, sensori fulmini e perdite richiedono decoder aggiuntivi.
- La pagina di configurazione è un server Web locale essenziale; non implementa ancora il reindirizzamento DNS automatico tipico dei captive portal.
- La ricezione è in polling su DIO0. Il pacchetto resta nel FIFO hardware fino alla lettura, quindi non è necessario eseguire Python dentro un interrupt.

## Riferimenti tecnici

- MicroPython, moduli C/C++ esterni: https://docs.micropython.org/en/latest/develop/cmodules.html
- MicroPython ESP32: https://docs.micropython.org/en/latest/esp32/quickref.html
- BresserWeatherSensorReceiver: https://github.com/matthias-bs/BresserWeatherSensorReceiver
- RadioLib SX1276: https://jgromes.github.io/RadioLib/class_s_x1276.html

Il decoder è un'implementazione autonoma del formato Bresser 5-in-1, basata sulla documentazione pubblica del protocollo e sui vettori di prova attribuiti nei test.

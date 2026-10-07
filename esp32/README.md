# BSG Gateway - MicroPython + ricevitore nativo

Questa cartella contiene il firmware ESP32 del gateway Bresser con:

- logica applicativa in MicroPython;
- configurazione Wi-Fi tramite pagina Web locale;
- invio JSON al server AMMS tramite HTTPS con verifica del certificato;
- ricevitore RFM95W/SX1276 e decoder Bresser 5-in-1 in C++ nativo;
- test del decoder eseguibili anche senza scheda ESP32.

## Stato del progetto

Il decoder Bresser 5-in-1 e l'interfaccia MicroPython sono implementati. Il driver nativo configura direttamente l'SX1276 in FSK a 868,3 MHz usando ESP-IDF, senza richiedere Arduino Core o RadioLib.

La parte radio deve essere validata sulla scheda reale, perché in questo ambiente non è collegato un ESP32 con RFM95W. Prima di sostituire un gateway operativo, confrontare per almeno alcune ore i valori ricevuti dal firmware precedente e da questo firmware.

## Hardware previsto

La configurazione predefinita replica il cablaggio documentato dal progetto originale:

| RFM95W | ESP32 D1 Mini |
|---|---:|
| RESET | GPIO32 |
| NSS / CS | GPIO27 |
| SCK | GPIO18 |
| MOSI | GPIO23 |
| MISO | GPIO19 |
| DIO0 | GPIO21 |
| DIO1 | GPIO33, non utilizzato da questa prima versione |
| 3.3V | 3.3V |
| GND | GND |

## Struttura

```text
esp32/
|-- boot.py
|-- main.py
|-- manifest.py
|-- config.example.json
|-- modules/
|   |-- config_store.py
|   |-- main_app.py
|   `-- wifi_manager.py
|-- native/
|   |-- micropython.cmake
|   `-- bresser_native/
|       |-- bresser_decoder.cpp/.hpp
|       |-- sx1276_receiver.cpp/.hpp
|       |-- modbresser_native.cpp
|       `-- micropython.cmake
|-- tests/
|   |-- CMakeLists.txt
|   `-- test_decoder.cpp
`-- BUILDING.md
```

Il client AMMS e i trasporti HTTPS sono forniti dal submodule `../external/AMMSUtils` e vengono congelati nel firmware dal manifest.

## API del modulo nativo

```python
import bresser_native

bresser_native.init(
    spi_host=3,
    sck=18,
    mosi=23,
    miso=19,
    cs=27,
    reset=32,
    dio0=21,
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
3. Copiare `config.example.json` sulla scheda come `/config.json` e inserire il token AMMS, oppure lasciare che il dispositivo apra la rete `Bresser Gateway`.
4. Collegarsi alla rete temporanea e aprire `http://192.168.4.1`.
5. Inserire Wi-Fi, token e URL API.

Non inserire token reali nei file versionati.

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

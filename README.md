# BSG Firmware v2 - MicroPython + ricevitore nativo

Questo repository contiene il firmware ESP32 del gateway Bresser con:

- logica applicativa in MicroPython;
- modalita AP permanente con captive portal, dashboard dati e output seriale;
- configurazione Wi-Fi tramite pagina Web locale nella modalita gateway;
- upload opzionale Weather Underground PWS o RapidFire;
- invio MQTT/TLS con payload JSON compatto e QoS 1;
- HTTPS firmato HMAC-SHA256 disponibile come fallback;
- ricevitore RFM95W/SX1276 e decoder Bresser 5-in-1 in C++ nativo;
- test del decoder eseguibili anche senza scheda ESP32.

## Stato del progetto

Il decoder Bresser 5-in-1 e l'interfaccia MicroPython sono implementati. Il driver nativo configura direttamente l'SX1276 in FSK a 868,3 MHz usando ESP-IDF, senza richiedere Arduino Core o RadioLib.

La parte radio deve essere validata sulla scheda reale, perché in questo ambiente non è collegato un ESP32 con RFM95W. Prima di sostituire un gateway operativo, confrontare per almeno alcune ore i valori ricevuti dal firmware precedente e da questo firmware.

## Hardware previsto

La configurazione predefinita e la build PlatformIO sono destinate a un
**ESP32-WROOM-32 con flash da almeno 4 MB, senza PSRAM**.
Il pinout proposto per il ricevitore RFM95W/SX1276 e il seguente;
verificare che corrisponda al cablaggio della propria scheda:

| RFM95W | ESP32-WROOM-32 |
|---|---:|
| RESET | GPIO14 |
| NSS / CS | GPIO27 |
| SCK | GPIO18 |
| MOSI | GPIO23 |
| MISO | GPIO19 |
| DIO0 | GPIO26 |
| 3.3V | 3.3V |
| GND | GND |

Il bus e `SPI2_HOST` (`spi_host=1`). DIO1 e DIO2 non sono utilizzati.
I GPIO6-11 sono riservati alla flash del WROOM-32.
Il pinout precedente della BSG Board v2 ESP32-S3 non si applica a questa build.
Per un cablaggio diverso modificare la sezione `radio` di `/config.json`.

La build usa ESP-IDF locale e MicroPython, senza Docker. Aprire la cartella
che contiene questo README e `build_firmware.py` nell'IDE preferito.
Lo stesso script funziona da terminale, VS Code, JetBrains ed Eclipse;
PlatformIO e un'integrazione opzionale. Il driver e il decoder Bresser
restano in C++ nativo e l'applicazione resta in MicroPython.
I sorgenti MicroPython vengono recuperati nella cache utente esterna,
mentre build e binari vanno in `.pio/`, esclusa da Git.
Vedere gli step di installazione in fondo a questo README.

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
    sck=18,
    mosi=23,
    miso=19,
    cs=27,
    reset=14,
    dio0=26,
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

## Avvio rapido in AP

1. Installare ESP-IDF e gli strumenti seguendo gli step in fondo al README.
2. Eseguire `python build_firmware.py build` nell'IDE preferito o nel terminale.
3. Usare `python build_firmware.py flash --port COM5`, poi
   `python build_firmware.py monitor --port COM5`, adattando la porta.
4. Collegarsi alla rete **Bresser Gateway** e aprire **http://192.168.4.1**
   se il captive portal non compare automaticamente.
5. Leggere i dati nella dashboard e sul monitor seriale. Non servono
   credenziali per usare questa modalita locale.

Il DNS wildcard e il reindirizzamento HTTP realizzano il captive portal;
l'apertura automatica varia tra sistemi operativi. La dashboard aggiorna i
valori ogni due secondi. `runtime.mode` vale `ap` per impostazione predefinita.

## Modalita gateway con upload remoto

Impostare `runtime.mode = "gateway"` in `/config.json` per usare gli invii
AMMS e Weather Underground descritti di seguito.


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
- La modalita AP include DNS captive e dashboard; la modalita gateway conserva il precedente server di configurazione essenziale.
- La ricezione è in polling su DIO0. Il pacchetto resta nel FIFO hardware fino alla lettura, quindi non è necessario eseguire Python dentro un interrupt.

## Riferimenti tecnici

- MicroPython, moduli C/C++ esterni: https://docs.micropython.org/en/latest/develop/cmodules.html
- MicroPython ESP32: https://docs.micropython.org/en/latest/esp32/quickref.html
- BresserWeatherSensorReceiver: https://github.com/matthias-bs/BresserWeatherSensorReceiver
- RadioLib SX1276: https://jgromes.github.io/RadioLib/class_s_x1276.html

Il decoder è un'implementazione autonoma del formato Bresser 5-in-1, basata sulla documentazione pubblica del protocollo e sui vettori di prova attribuiti nei test.

## Installazione completa e uso da qualsiasi IDE

Questa procedura mantiene **MicroPython + bresser_native C++**. Non richiede
Docker, WSL o Arduino. Il protocollo Bresser 5-in-1, la modulazione FSK,
la frequenza 868,3 MHz, i controlli di parita/checksum e le API del modulo
restano quelli della libreria esistente. Non vengono aggiunti decoder per
altri protocolli: la sola frequenza 868 MHz non rende compatibili tutte le
stazioni meteo.

### 1. Installare gli strumenti di base

Installare **Git** e **Python 3.11 a 64 bit**, abilitando Python nel PATH.
Installare il driver USB/seriale del chip della propria scheda (CP210x o CH340,
secondo l'hardware). Chiudere e riaprire il terminale dopo le installazioni.
Verificare:

```sh
git --version
python --version
```

### 2. Recuperare il progetto e AMMSUtils

Per il repository destinazione:

```sh
git clone --recurse-submodules https://github.com/SMAS-APS/BSG-Firmware-v2.git
cd BSG-Firmware-v2
git submodule update --init --recursive
```

Nella copia di lavoro attuale, entrare invece nella cartella
`BSG-Firmware-v2-main`, senza rinominarla o spostarla.
Tutti i comandi seguenti vanno eseguiti nella cartella che contiene
`build_firmware.py`, `manifest.py`, `modules` e `native`.

### 3. Installare ESP-IDF v5.5.2 sul PC

Windows, da PowerShell, con Git e Python nel PATH:

```powershell
$env:BSG_IDF_PATH = Join-Path $env:USERPROFILE ".espressif/bsg/esp-idf-v5.5.2"
git clone --depth 1 --branch v5.5.2 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git $env:BSG_IDF_PATH
& "$env:BSG_IDF_PATH/install.bat" esp32
& "$env:BSG_IDF_PATH/export.ps1"
```

Non ripetere `git clone` se quella directory contiene gia ESP-IDF v5.5.2.
Usare invece l'installazione esistente e impostare `BSG_IDF_PATH` al suo percorso.
Se PowerShell blocca `export.ps1`, eseguire soltanto per quella sessione:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& "$env:BSG_IDF_PATH/export.ps1"
```

Linux/macOS, da terminale:

```sh
export BSG_IDF_PATH="$HOME/.espressif/bsg/esp-idf-v5.5.2"
git clone --depth 1 --branch v5.5.2 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git "$BSG_IDF_PATH"
"$BSG_IDF_PATH/install.sh" esp32
. "$BSG_IDF_PATH/export.sh"
```

Su Linux installare anche i prerequisiti di sistema della
[guida ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/v5.5.2/esp32/get-started/linux-macos-setup.html).
Su Windows e disponibile anche l'[installer ufficiale ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/v5.5.2/esp32/get-started/windows-setup.html):
selezionare v5.5.2 e aprire il terminale ESP-IDF creato dall'installer.
La toolchain rimane fuori dal repository.

### 4. Installare i pacchetti Python della build

Dal terminale ESP-IDF attivato, tornare nella cartella del progetto:

```sh
python -m pip install -r requirements-build.txt
python build_firmware.py doctor
python build_firmware.py prepare
```

`mpy-cross` contiene il compilatore di bytecode MicroPython gia compilato
per il PC, con versione compatibile con MicroPython v1.29.0.
`mpremote` serve per REPL e gestione dei file sulla scheda.
`prepare` recupera MicroPython v1.29.0 e le sue dipendenze nella cache
utente `~/.cache/bsg-firmware`, esterna al repository.
Su Windows adatta nella cache solo la pipeline QSTR della build, usando
Python e CMake al posto dei comandi Unix `cat`, `sed` e `touch`, con file
di argomenti/risposta per evitare i limiti di lunghezza dei comandi Windows.
La libreria Bresser non viene riscritta.

### 5. Verificare il cablaggio

ESP32-WROOM-32 con almeno 4 MB di flash, RFM95W/SX1276 a 3,3 V e massa comune:
SCK GPIO18, MOSI GPIO23, MISO GPIO19, CS GPIO27, RESET GPIO14, DIO0 GPIO26.
Confrontare sempre con lo schema della propria scheda. I GPIO6-11 sono
riservati alla flash. Per pin diversi aggiornare i valori `radio` nel
`config.example.json` e nel `modules/config_store.py`, oppure usare
`/config.json` sulla scheda. La frequenza predefinita e 868,3 MHz.

### 6. Compilare il firmware

```sh
python build_firmware.py build
```

Lo script compila MicroPython con `BOARD=ESP32_GENERIC`, include
`native/micropython.cmake` e congela i file del `manifest.py`.
Il risultato e `.pio/build/esp32-wroom-32/firmware.bin`.
Non vengono compilati i file Python come un'applicazione Arduino.

Se ESP-IDF non viene trovato, passare il percorso esplicito:

```sh
python build_firmware.py build --idf-path "C:/percorso/esp-idf-v5.5.2"
```

`BSG_IDF_PATH`, `IDF_PATH` o `--idf-path` consentono di usare una propria
installazione. Il percorso predefinito della procedura sopra viene trovato
automaticamente anche da un terminale dell'IDE non ancora attivato.
I pacchetti `requirements-build.txt` devono essere installati nel Python ESP-IDF.

### 7. Caricare e aprire la seriale

Collegare la scheda via USB e individuare la porta. Sostituire `COM5` con
quella effettiva (su Linux, per esempio `/dev/ttyUSB0`).

```sh
python build_firmware.py flash --port COM5
python build_firmware.py monitor --port COM5
```

`flash` compila prima del caricamento e usa la mappa flash di ESP-IDF.
Chiudere il monitor prima di un nuovo caricamento. Se necessario, tenere
premuto BOOT all'inizio del collegamento e rilasciarlo quando inizia la scrittura.
Uscire dal monitor ESP-IDF con `Ctrl+]`.

Solo alla prima installazione da un firmware diverso puo servire cancellare
la flash; questo elimina anche configurazione e dati salvati:

```sh
python -m esptool --chip esp32 --port COM5 erase_flash
python build_firmware.py flash --port COM5
```

### 8. Aprire il captive portal AP

Collegarsi alla rete aperta **Bresser Gateway**. Aprire il captive portal
mostrato dal sistema, oppure **http://192.168.4.1** nel browser.
La pagina mostra i dati e si aggiorna ogni due secondi. Il serial monitor
a **115200 baud** stampa ogni pacchetto valido ricevuto.
L'apertura automatica del captive portal dipende da telefono/PC; resta
sempre disponibile l'indirizzo HTTP diretto.

`runtime.mode` vale `ap` per default e non richiede credenziali AMMS.
Il portale resta disponibile anche in caso di errore radio.
Le configurazioni gia salvate possono contenere i vecchi pin ESP32-S3:
aggiornarle prima dell'uso. Il file `/config.json` non viene copiato automaticamente.

### 9. Configurare l'IDE preferito

**JetBrains (PyCharm, IntelliJ o CLion):** aprire la cartella del progetto.
Usare il terminale integrato oppure aggiungere un External Tool con programma
`python` (o il percorso assoluto di Python), argomenti `build_firmware.py build`
e working directory impostata alla radice del progetto. Creare strumenti
analoghi per `flash --port COM5` e `monitor --port COM5`.
Per completamento Python selezionare l'interprete ESP-IDF; i moduli `machine`
e `network` sono disponibili sulla scheda, non nel Python del PC.

**Eclipse:** importare la cartella come progetto e aggiungere External Tools
con programma `python`, working directory del progetto e gli stessi argomenti.
La build usa CMake/ESP-IDF tramite lo script, indipendentemente dall'editor.

**VS Code:** usare gli stessi comandi nel terminale, o aggiungere task che
richiamino lo script. Con PlatformIO IDE, aprire la cartella con `platformio.ini`:
Build e Upload sono collegati alla stessa compilazione ESP-IDF locale.
PlatformIO resta opzionale; non occorre installarlo per JetBrains o Eclipse.

**Altri editor/IDE:** basta poter avviare Python o un comando esterno.
Questa e una build tramite strumenti esterni, non un plugin specifico per ogni IDE.

### 10. Test e pubblicazione su GitHub

```sh
python -m unittest discover -s tests -p "test_*.py"
git status --short
```

Il repository destinazione e [SMAS-APS/BSG-Firmware-v2](https://github.com/SMAS-APS/BSG-Firmware-v2).
Versionare sorgenti, script, configurazioni di build e documentazione.
AMMSUtils resta un submodule. `.pio/`, binari, cache, configurazioni con
credenziali e toolchain non devono essere caricati nel repository.
La parte radio e il captive portal devono essere validati sulla scheda reale.

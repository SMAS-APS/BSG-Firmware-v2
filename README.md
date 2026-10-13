# BSG Firmware v2 - versione 0.1.0

**Stato: test avanzato su ESP32-WROOM-32 con modulo RF collegato.**

**Per installare la scheda rapidamente:** aprire [GUIDA_FLASH.md](GUIDA_FLASH.md) e usare il menu `bsg.cmd`.

Questo repository contiene il firmware ESP32 del gateway Bresser con:

- logica applicativa in MicroPython;
- modalita AP permanente con captive portal, dashboard dati e output seriale;
- configurazione Wi-Fi, AMMS, MQTT/TLS e Wunderground dalla dashboard AP;
- upload opzionale Weather Underground PWS o RapidFire;
- invio MQTT/TLS con payload JSON compatto e QoS 1;
- HTTPS firmato HMAC-SHA256 disponibile come fallback;
- ricevitore RFM95W/SX1276 e decoder Bresser 5-in-1 nativo, con estensioni 6/7-in-1 in MicroPython;
- test su vettori RF, configurazione, LED, captive portal e invii simulati eseguibili senza scheda ESP32.

## Stato del progetto

Il decoder Bresser 5-in-1 nativo e le estensioni MicroPython 6/7-in-1 sono implementati. Il driver nativo configura direttamente l'SX1276 in FSK a 868,3 MHz usando ESP-IDF, senza richiedere Arduino Core o RadioLib.

Il firmware **0.1.0** e in fase di test avanzato sulla scheda ESP32-WROOM-32
con modulo RF collegato. Versione e fase sono riportate sulla seriale, nella
dashboard e nell'API `/api/readings`. La ricezione di pacchetti reali, la
stabilita e il captive portal vanno verificati durante le sessioni di test;
la presenza del modulo RF non equivale alla validazione completa del sistema.

## Configurazione dal pannello di controllo

La dashboard scura, ispirata alle console SALZEN e Power Monitor, è disponibile
su **http://192.168.4.1** nell'AP e sull'indirizzo IP della scheda nella rete del router.
Il server si avvia in tutte le modalità, anche senza credenziali remote o con errore RF.

- **Stato:** grafici esclusivamente per le misure numeriche trasmesse dalla stazione
  selezionata. Modelli con meno sensori non mostrano schede vuote. Espansione, tooltip,
  zoom, scorrimento ed esportazione CSV. La direzione del vento usa una rosa dei venti
  con provenienza, nome del vento e frequenza dei settori nella vista espansa; massimo 360 campioni per ciascuna delle ultime
  8 stazioni nella sessione del browser. Lo storico non è persistente sulla flash.
- **Wi-Fi:** scansione in background di tutti gli access point 2,4 GHz rilevati,
  icone Google Material locali, qualità stimata dal RSSI e potenza ricevuta in dBm.
  Le reti aperte selezionate eliminano la password precedente. Le reti nascoste
  possono richiedere l'SSID manuale; anche gli spazi del nome sono conservati.
  Credenziali salvate senza disabilitare l'AP, applicate dopo il riavvio.
- **Impostazioni:** token AMMS/WU, HTTPS o MQTT/TLS, CA PEM, frequenze, monitor seriale,
  riavvio e orologio. I segreti non vengono restituiti al browser; lasciarli vuoti
  conserva quelli salvati. Il Wi-Fi e i servizi hanno pulsanti di salvataggio distinti.
- **Terminale:** log applicativo limitato a 12.000 caratteri / 120 voci, autoscroll,
  frequenza output, cronologia comandi. `help`, `status`, `sensors`, `stations`,
  `battery`, `wifi`, `wifi scan`, `radio`, `heap`, `uptime`, `time`, `ntp sync`,
  `serial 0|1|5|10|30|60`, `monitor`, `clear`, `restart`/`reboot`/`reset`, `exit`.
  Errori e diagnostica sono nel terminale; non esiste una scheda Alert.

La batteria della stazione usa il flag RF reale **OK/LOW**, distinto per sensore,
con indicazione dell'età dell'ultimo dato. I protocolli 5/6/7-in-1 supportati non
forniscono percentuale né tensione: non vengono ricavate da questo flag.
Vedere la [documentazione del decoder di riferimento](https://github.com/matthias-bs/BresserWeatherSensorReceiver#home-assistant).

In **Data e ora** si configurano server NTP, abilitazione, intervallo e fuso.
`Europe/Rome` gestisce automaticamente CET/CEST; disponibili anche Paris, Berlin,
Madrid, London, Athens, UTC e un offset personalizzato fisso. La RTC conserva UTC;
il fuso viene applicato alla visualizzazione e al conteggio giornaliero della pioggia.
Le regole europee usano l'ultima domenica di marzo e ottobre, alle 01:00 UTC.
L'orologio viene sincronizzato in background anche se AMMS/WU sono disabilitati;
serve una connessione Internet sul Wi-Fi STA. Solo AP: dashboard sempre utilizzabile,
orologio indicato come non sincronizzato finché non è disponibile un'ora valida.
Orologio e frequenze si applicano senza riavvio, Wi-Fi e servizi con riavvio.

Per un'anteprima desktop, senza scritture sulla scheda né sulla configurazione:

```sh
python tools/preview_dashboard.py --model 5
```

Aprire **http://127.0.0.1:8765**. L'anteprima indica esplicitamente che i dati
sono simulati. `--model 7` aggiunge UV e luminosità. Interrompere con Ctrl+C.
Le icone SVG Google Material sono incluse nel sorgente per funzionare nell'AP
senza Internet; licenza in `MATERIAL-ICONS-LICENSE.txt` e provenienza in
`MATERIAL-ICONS-NOTICES.md`.

AMMS e Wunderground hanno abilitazioni indipendenti. HTTPS e MQTT sono
trasporti alternativi dello stesso client AMMS; il formato e i topic originali
`amms/v1/stations/<station_id>/telemetry` e `/status` rimangono invariati.
MQTT usa l'ID stazione come utente, la chiave HMAC come password, TLS e QoS 1.
Password, token e chiavi salvate non sono mostrati nel browser: un campo
segreto vuoto conserva il valore esistente. Cambiando SSID bisogna inserire
la password della nuova rete; per una rete aperta usare la relativa casella.

Il salvataggio sostituisce atomicamente il JSON. Un nuovo PEM usa un file CA
separato per conservare il certificato precedente se il salvataggio fallisce.
Gli invii HTTPS/MQTT, la sincronizzazione NTP e la scansione Wi-Fi usano worker separati; radio, DNS e HTTP
continuano nel ciclo principale. Gli invii attendono rete e orologio validi.
La prima **stazione meteo** riconosciuta dopo il riavvio viene scelta per gli
invii; gli altri ID restano visibili sulla seriale e nell'API e non vengono
mescolati nello stesso upload. Dati piu vecchi di 120 secondi non vengono inviati.

## Recupero Wi-Fi dalla seriale

Aprire il monitor a **115200 baud** (`python bsg.py monitor --port COM3`,
sostituendo la porta effettiva) e digitare **config** seguito da Invio.
Il firmware richiede prima **SSID**, poi **password**; password vuota significa rete
aperta. Il nome può appartenere anche a una rete nascosta. La password viene
mascherata e non viene copiata nel registro del terminale. Il salvataggio conserva
AMMS/WU e forza la connessione al router **senza riavviare la scheda**.
Al successo la seriale mostra l'IP della scheda sulla rete del router.
Il comando funziona anche da altri terminali seriali: lettura non bloccante nel
ciclo del firmware. `help` mostra gli altri comandi, Ctrl-C interrompe l'applicazione.
Aggiornare tutti i moduli Python con `bsg.py deploy` prima di usarlo su immagini
precedenti; una modifica GitHub da sola non aggiorna il filesystem dell'ESP32.

L'AP viene avviato aperto sul canale 1, con massimo 4 client; in modalità AP + STA
il canale segue quello del router quando viene stabilita la connessione.
La connessione automatica attende 10 secondi all'avvio. Tentativi falliti usano
intervalli crescenti e vengono sospesi quando qualcuno è collegato all'AP o durante
una scansione; `config` forza comunque il tentativo esplicito. Il driver non effettua
riconnessioni infinite in parallelo. La seriale segnala stato e variazioni di canale.
Errori per singola richiesta HTTP, inclusa memoria insufficiente, chiudono solo
quella richiesta e lasciano AP, ricevitore e comandi seriali in esecuzione.
Queste protezioni non sostituiscono il registro hardware per diagnosticare reset,
alimentazione insufficiente o problemi del driver Wi-Fi del PC.

## Autoriconoscimento e diagnostica RF

| Famiglia radio | Varianti decodificate |
|---|---|
| 5-in-1 | Stazioni con formato originale e pluviometro professionale (tipi 0x39..0x3B) |
| 6-in-1 | Stazione meteo / anemometro 3-in-1, termoigrometro, termometro piscina, sensore suolo |
| 7-in-1 | Stazione 7-in-1, 3-in-1 temperatura/umidita/pioggia, 8-in-1, sensori PM/CO2/HCHO-VOC |

Il riconoscimento verifica parita/checksum per 5-in-1 e digest LFSR/checksum
per 6/7-in-1. Il nome identifica **famiglia e tipo sensore**, non necessariamente
il modello commerciale della console. I messaggi alternati 6-in-1 vengono
uniti per protocollo, ID e canale, con scadenza dei singoli campi a 120 secondi.
Non vengono inventati vento o umidita per sensori che non li misurano.

La seriale a 115200 baud stampa versione **0.1.0**, fase **test-avanzato**,
pin radio, famiglia, ID, canale, batteria, RSSI e misure ricevute. Un frame
corrotto/non supportato stampa **ERRORE RF** e incrementa il contatore nella
pagina; il ciclo continua a cercare. L'assenza di pacchetti significa attesa,
non un errore di protocollo.

Il LED utente della Wemos D1 mini32 usa **GPIO2**, con impulsi di 100 ms per
ogni frame ricevuto, inclusi quelli non riconosciuti. Il lampeggio non blocca
il ciclo. `runtime.led_pin`, `led_active_low` e `led_pulse_ms` permettono di
adattare eventuali varianti della scheda; il valore predefinito e attivo alto.

**Aggiornamento da un'immagine precedente:** questa estensione aggiunge
`bresser_native.poll_raw()`: compilare e flashare una volta la nuova immagine
(voce 6, poi 2 di `bsg.cmd`, senza cancellazione completa). Per i successivi
cambiamenti Python basta la voce 3. Il caricatore verifica la nuova API prima
di copiare file; il decoder C++ 5-in-1 e le sue API precedenti restano invariati.
Il vecchio pinout predefinito RESET14/DIO0 26 viene migrato automaticamente a
RESET32/DIO0 21/DIO1 33. I cablaggi personalizzati sono conservati.

## Correzione ricezione RF e seriale — driver revisione 2

Il monitor del menu (voce 4) apre ora COM prima di riavviare Python, cosi non
perde i messaggi iniziali. Ogni 10 secondi il firmware stampa versione, numero
pacchetti, errori, tempo dall'ultima lettura e diagnostica del ricevitore.
`python serial_monitor.py --port COM3 --no-restart` osserva senza riavvio.

Il confronto con `WeatherSensor.cpp` originale e `RadioLib::beginFSK()` ha
riallineato `RxConfig` a **0x09** (AGC automatico, trigger RSSI, AFC automatico
disabilitato) e `SyncConfig` a **0x91** (AA, sync AA 2D, due byte, bit riservato 3
azzerato). Sono espliciti RSSI a 2 campioni, preamble detector e timeout spenti.
Ogni impostazione viene riletta per verificare la comunicazione SPI. Il
pacchetto e ancora di 27 byte: D4 residuo del sync piu 26 byte di payload.

Il driver legge `PayloadReady` dal registro IRQ anche con DIO0 basso, e conta
queste anomalie in `dio0_misses`. Recupera un FIFO overrun svuotando il FIFO
prima di riavviare RX; non svuota mai un pacchetto durante la diagnostica.
`bresser_native.diagnostics()` e `/api/readings` riportano `rx_active`, RSSI
istantaneo, IRQ1/IRQ2, livelli DIO, configurazione sync/RX e contatori.
Il valore 4 o 5 di OpMode in FSK e interpretato correttamente come ricezione,
come il workaround RadioLib per il bit 0 instabile.

**Test reale del 12 ottobre 2026**, ESP32/RFM95W su COM3 con il pinout sopra:
la configurazione precedente non ha prodotto frame in 60 secondi; quella
riallineata ha prodotto 6 frame in 60 secondi, inclusi messaggi checksum validi
famiglia 6-in-1, ID `0x311440A3`, temperatura circa 16,8 C e umidita 57–58%.
Il protocollo radio e il nome commerciale della console non sono equivalenti.
Questa verifica non costituisce un test di portata o di tutti i modelli.

Per aggiornare dalla prima immagine 0.1.0, compilare (voce 6) e flashare
(voce 2) **senza CANCELLA**. La metadata indica `rf_driver_revision: 2`;
la sola copia di file Python non aggiorna i registri del driver nativo.

Fonti: [WeatherSensor.cpp](https://github.com/matthias-bs/BresserWeatherSensorReceiver/blob/main/src/WeatherSensor.cpp),
[RadioLib SX127x](https://github.com/jgromes/RadioLib/blob/master/src/modules/SX127x/SX127x.cpp),
[datasheet Semtech SX1276, registri FSK](https://www.laskakit.cz/user/related_files/ds_sx1276-7-8-9_w_app_v7.pdf).

## Hardware previsto

La configurazione predefinita e la build PlatformIO sono destinate a un
**ESP32-WROOM-32 con flash da almeno 4 MB, senza PSRAM**.
Il cablaggio del modulo RFM95W-915S2 collegato alla Wemos ESP32 mini e il seguente;
verificare che corrisponda al cablaggio della propria scheda:

| RFM95W | ESP32-WROOM-32 |
|---|---:|
| RESET | GPIO32 |
| NSS / CS | GPIO27 |
| SCK | GPIO18 |
| MOSI | GPIO23 |
| MISO | GPIO19 |
| DIO0 | GPIO21 |
| DIO1 | GPIO33 |
| 3.3V | 3.3V |
| GND | GND |

Il bus e `SPI2_HOST` (`spi_host=1`). DIO1 GPIO33 e configurato come ingresso; la ricezione usa PayloadReady su DIO0. DIO2 non e utilizzato.
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
|-- bsg.py / bsg.cmd / bsg.ps1
|-- GUIDA_FLASH.md
|-- build_firmware.py
|-- requirements-build.txt / requirements-tools.txt
|-- platformio.ini
|-- boot.py
|-- main.py
|-- manifest.py
|-- config.example.json
|-- modules/
|   |-- bsg_runtime.py
|   |-- config_store.py
|   |-- main_app.py
|   |-- mqtt_transport.py
|   |-- wifi_manager.py
|   `-- wu_support.py
|-- native/
|   |-- boot.py / main.py (avvio congelato aggiornabile)
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
    reset=32,
    dio0=21,
    dio1=33,
    frequency_hz=868_300_000,
)

reading = bresser_native.poll()
if reading:
    print(reading)
```

`poll()` non blocca: restituisce `None` quando non è pronto un pacchetto valido. Quando riceve un messaggio 5-in-1 valido restituisce un dizionario con temperatura, umidità, vento, pioggia, batteria, RSSI e payload grezzo.

Sono inoltre disponibili:

- `bresser_native.decode(payload)` per provare un payload di 26 byte senza radio;
- `bresser_native.poll_raw()` per frame grezzi, RSSI e controllo sync; usato da `AutoReceiver` per 5/6/7-in-1;
- `bresser_native.stats()` per contatori nativi; gli errori di riconoscimento Python sono in `/api/readings`;
- `bresser_native.status()` per configurazione e versione del chip;
- `bresser_native.diagnostics()` per stato reale dei registri RX, RSSI e IRQ;
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

## Modalita gateway legacy

La modalita AP ora supporta gli invii remoti e resta la scelta predefinita.
La precedente modalita `runtime.mode = "gateway"` e conservata per le
configurazioni esistenti; i passaggi manuali seguenti riguardano quella modalita.


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

- Autoriconoscimento 5-in-1, 6-in-1 e 7-in-1 con le varianti elencate sopra.
- I sensori fulmini e perdite e i protocolli diversi non sono decodificati: un frame non riconosciuto genera ERRORE RF.
- La modalita AP include DNS captive e dashboard; la modalita gateway conserva il precedente server di configurazione essenziale.
- La ricezione è in polling su DIO0. Il pacchetto resta nel FIFO hardware fino alla lettura, quindi non è necessario eseguire Python dentro un interrupt.

Attribuzioni degli algoritmi e licenze: [BRESSER-NOTICES.md](BRESSER-NOTICES.md).
LED GPIO2: [variante ufficiale Espressif D1 mini32](https://github.com/espressif/arduino-esp32/blob/master/variants/d1_mini32/pins_arduino.h).

## Riferimenti tecnici

- MicroPython, moduli C/C++ esterni: https://docs.micropython.org/en/latest/develop/cmodules.html
- MicroPython ESP32: https://docs.micropython.org/en/latest/esp32/quickref.html
- BresserWeatherSensorReceiver: https://github.com/matthias-bs/BresserWeatherSensorReceiver
- RadioLib SX1276: https://jgromes.github.io/RadioLib/class_s_x1276.html

Il decoder è un'implementazione autonoma del formato Bresser 5-in-1, basata sulla documentazione pubblica del protocollo e sui vettori di prova attribuiti nei test.

## Installazione completa e uso da qualsiasi IDE

Questa procedura mantiene **MicroPython + bresser_native C++**. Non richiede
Docker, WSL o Arduino. Il decoder Bresser 5-in-1 e la modulazione FSK,
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
Il firmware, il programma di caricamento e la guida sono disponibili nel branch `main`.

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
SCK GPIO18, MOSI GPIO23, MISO GPIO19, CS GPIO27, RESET GPIO32, DIO0 GPIO21.
DIO1 GPIO33; LED utente GPIO2. Confrontare con lo schema della scheda. I GPIO6-11 sono
riservati alla flash. Per pin diversi aggiornare i valori `radio` nel
`config.example.json` e nel `modules/config_store.py`, oppure usare
`/config.json` sulla scheda. La frequenza predefinita e 868,3 MHz.

### 6. Compilare il firmware

```sh
python build_firmware.py build
```

Lo script compila MicroPython con `BOARD=ESP32_GENERIC`, include
`native/micropython.cmake` e congela i file del `manifest.py`. Gli avvii
congelati delegano a `/boot.py` e `/main.py` quando presenti, e i moduli
del filesystem hanno precedenza: gli aggiornamenti Python non richiedono
una nuova build C++.
Il risultato e `.pio/build/esp32-wroom-32/firmware.bin`, con il suo
`firmware.bin.json` per la verifica di scheda e SHA256.
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

`flash` compila prima del caricamento, verifica lo SHA256, scrive la nuova
immagine combinata a 0x1000 e trasferisce anche i file Python aggiornati.
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

### 11. Aggiornare il Python senza ricompilare

Dopo l'installazione dell'immagine aggiornata, usare il menu `bsg.cmd`
(voce 3), oppure:

```sh
python bsg.py deploy --port COM5
```

Lo strumento aggiorna gli script nel filesystem, verifica prima la presenza
del modulo nativo Bresser, conserva configurazione/certificati e riavvia la
scheda. Non modifica il C++ e non cancella la flash.
Per installare un'immagine gia compilata senza ESP-IDF:

```sh
python -m pip install -r requirements-tools.txt
python bsg.py ports
python bsg.py flash --port COM5
python bsg.py monitor --port COM5
```

Aggiungere `--erase` a `flash` solo quando si vuole cancellare tutta la flash,
per esempio nella prima installazione da un firmware diverso.
La guida semplificata completa e [GUIDA_FLASH.md](GUIDA_FLASH.md).

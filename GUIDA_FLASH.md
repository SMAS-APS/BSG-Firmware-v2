# Installare MicroPython+Bresser e aggiornare il programma

**Firmware 0.2.0 - test avanzato con ESP32, modulo RF e bootstrap OTA A/B.**

Nell'ambiente di test gia operativo usare normalmente il flash **senza `--erase`**
e premere Invio alla richiesta CANCELLA, per conservare configurazione e dati.

Questa scheda usa **ESP32-WROOM-32**, con almeno 4 MB di flash.
Il collegamento USB e una **porta seriale**, non una chiavetta USB.

Per questo progetto l'immagine da installare e **MicroPython con la libreria
Bresser gia incorporata**. Non occorre installare prima un altro MicroPython.
L'immagine standard scaricata dal sito MicroPython non contiene `bresser_native`
e non permette a questo firmware di usare la radio.

## Percorso piu semplice su questo PC

La cartella del progetto e `BSG-Firmware-v2-main`.
L'immagine aggiornata e gia compilata in
`.pio/build/esp32-wroom-32/firmware.bin`, insieme al suo `firmware.bin.json`.
Gli strumenti sono installati nell'ambiente Python ESP-IDF del PC.

1. Collega la scheda con un **cavo USB dati**. Chiudi Thonny, monitor seriali
   e altri programmi che stanno usando la porta della scheda.
2. Fai doppio clic su **`bsg.cmd`** nella cartella del progetto.
3. Scegli **1 - Porte USB** e identifica la scheda, per esempio `COM5`.
   Se non riconosci la porta, scollega e ricollega il cavo e confronta l'elenco.
4. Scegli **2 - Installa MicroPython+Bresser** e seleziona la porta della scheda.
5. Se e la prima installazione da Arduino o da un firmware diverso, scrivi
   **CANCELLA** quando il menu lo propone. Questo elimina anche tutti i dati
   e le configurazioni precedenti. Per un aggiornamento con dati da conservare,
   premi Invio senza scrivere CANCELLA.
6. Attendi la scrittura. Se compare `Connecting...` e non prosegue, tieni
   premuto **BOOT**; se necessario premi e rilascia **EN/RESET**, poi rilascia
   BOOT quando inizia la scrittura.
7. Lo strumento carica anche i file Python aggiornati e riavvia la scheda.
8. Scegli **4 - Monitor seriale**. Vedrai i messaggi a **115200 baud**.
9. Collegati alla rete Wi-Fi **Bresser Gateway**. Il sistema puo aprire il
   captive portal automaticamente; altrimenti apri **http://192.168.4.1**.

Non serve avviare VS Code o un altro IDE per questa procedura.
Nessun comando di flash viene eseguito automaticamente quando apri il menu.

## Gli stessi passaggi da terminale

Windows, da PowerShell nella cartella `BSG-Firmware-v2-main`:

```powershell
.\bsg.cmd ports
.\bsg.cmd flash --port COM5 --erase
.\bsg.cmd monitor --port COM5
```

Sostituisci `COM5` con la porta corretta. **`--erase` cancella tutta la flash**:
omettilo negli aggiornamenti quando vuoi mantenere i dati.
Il launcher individua il Python ESP-IDF installato e gestisce anche il caso
in cui `python` non sia nel PATH di Windows.

Linux/macOS, o qualunque IDE con Python configurato:

```sh
python bsg.py ports
python bsg.py flash --port /dev/ttyUSB0 --erase
python bsg.py monitor --port /dev/ttyUSB0
```

Su macOS la porta sara simile a `/dev/cu.usbserial-...`.

## Dopo la prima installazione: aggiorna solo il Python

Puoi modificare l'interfaccia Web, la logica applicativa, `boot.py` e `main.py`
nell'IDE che preferisci. Poi scegli **3 - Aggiorna solo i file Python** nel
menu, oppure esegui:

```powershell
.\bsg.cmd deploy --port COM5
```

Su altri sistemi: `python bsg.py deploy --port PORTA`.

Questo comando:

- verifica che sulla scheda ci sia il firmware MicroPython+Bresser compatibile;
- copia `boot.py`, `main.py`, i moduli applicativi e AMMSUtils;
- sostituisce ogni file solo dopo che la sua copia temporanea e completa;
- conserva `/config.json`, certificati e stato pluviometrico;
- riavvia l'ESP32, che esegue il programma aggiornato.

**Non ricompila C++ e non cancella la flash.** Se il trasferimento si
interrompe, ripeti il comando. La libreria radio rimane nell'interprete.
I moduli Python nel filesystem hanno precedenza sulla copia inclusa nell'immagine.
Anche `boot.py` e `main.py` vengono eseguiti dal filesystem quando presenti.

Il comando `deploy` della versione 0.2.0 prepara inoltre `/ota/a`, installa lo
stato A/B e costituisce il bootstrap necessario per gli aggiornamenti remoti.
Da quel momento le release `.ammsfw` possono essere caricate e distribuite
dalla console amministrativa AMMSServer. Il comando USB rimane la procedura di
recupero e l'unico modo per aggiornare MicroPython o il driver radio nativo.
In loro assenza viene avviata l'applicazione inclusa nel firmware.

Non eseguire `main.py` con il Python del PC: `network`, `machine` e
`bresser_native` sono moduli della scheda. L'IDE modifica i file; l'ESP32 li esegue.

## Quando serve ricompilare l'immagine

Ricompila se modifichi la libreria C++ Bresser, la versione MicroPython,
la configurazione ESP-IDF o vuoi distribuire una nuova immagine completa.
Nel menu scegli **6 - Compila l'immagine con ESP-IDF**, oppure:

```sh
python build_firmware.py build
```

Poi usa nuovamente la voce 2 del menu. Il flash scrive l'immagine combinata
a **0x1000**, in modalita DIO, e aggiorna anche i file Python: non lascia attiva
una vecchia copia dell'applicazione nel filesystem.
Il file `.bin.json` contiene il tipo di scheda, la presenza della libreria
nativa e lo SHA256. Viene verificato prima di scrivere o cancellare la scheda.
Conserva sempre insieme `firmware.bin` e `firmware.bin.json`.

Le immagini della prima versione preparata prima di questa guida non hanno
il nuovo avvio aggiornabile. Su quelle schede serve un nuovo flash dell'immagine
aggiornata, una volta sola, prima di usare `deploy`.

## Installazione degli strumenti su un altro PC

Per usare un'immagine gia compilata servono solamente **Python 3.11**, il
driver USB/seriale della scheda e gli strumenti leggeri:

```sh
python -m pip install -r requirements-tools.txt
```

In alternativa, su Windows apri `bsg.cmd` e scegli **7 - Installa gli strumenti USB**.
Il menu deve poter trovare un Python installato sul PC.
Per il flash e gli aggiornamenti Python **non serve ESP-IDF**.
Servono il progetto completo, la libreria `external/AMMSUtils` e la coppia
`firmware.bin`/`firmware.bin.json` generata da una build verificata.

Per compilare l'immagine sul nuovo PC installa anche **ESP-IDF v5.5.2** e
i pacchetti `requirements-build.txt`: tutti gli step sono in fondo al
[README](README.md#installazione-completa-e-uso-da-qualsiasi-ide).
Non sono richiesti Docker o WSL. JetBrains, Eclipse e VS Code possono
richiamare gli stessi comandi dal terminale o come strumenti esterni.

## Verifiche e problemi comuni

| Situazione | Cosa fare |
|---|---|
| Nessuna porta USB | Usa un cavo dati; controlla alimentazione e driver CP210x/CH340 secondo la scheda. |
| Porta occupata / access denied | Chiudi gli altri monitor seriali e Thonny, poi riprova. |
| Bloccato su Connecting | Usa BOOT e EN/RESET come descritto sopra. |
| Nessuna immagine o manca .bin.json | Compila con la voce 6 oppure recupera entrambi i file della stessa build. |
| SHA256 non corrispondente | Recupera la coppia originale o ricompila; non usare file di build diverse. |
| ImportError: bresser_native | Sulla scheda manca la libreria: installa l'immagine personalizzata di questo progetto. |
| ImportError: bsg_runtime | L'immagine e precedente al nuovo avvio aggiornabile: esegui una volta il nuovo flash. |
| Errore GPIO6-11 riservati | La configurazione contiene pin ESP32-S3: aggiornare la sezione radio di /config.json. |
| Errore SX1276, ma pagina Web visibile | Controlla radio a 3,3 V, massa, CS, RESET, SPI e DIO0; il portale resta disponibile. |
| Wi-Fi AP non mostra automaticamente la pagina | Rimani connesso alla rete senza Internet e apri http://192.168.4.1. |
| Serial monitor vuoto | Usare la voce 4 aggiornata; si riavvia Python dopo avere aperto la porta. Attendere lo stato periodico entro 10 secondi. |
| Nessun dato meteo | Verifica antenna 868 MHz, cablaggio e sensore Bresser 5/6/7-in-1 compatibile; attendi i suoi pacchetti. |

Puoi verificare la presenza di MicroPython e della libreria con la voce 5,
oppure `bsg.cmd check --port COM5`. Questa verifica non prova la ricezione RF.

La voce **4** ora apre la porta prima di riavviare Python: versione, pin e
messaggi di avvio vengono catturati subito. Non cancella dati o credenziali.
Nel monitor: **Ctrl-C** ferma l'applicazione e apre il REPL; **Ctrl-D** la
riavvia; **Ctrl-]** esce. Il firmware stampa uno stato ogni **10 secondi**, anche
senza pacchetti. Per osservare senza riavviare: `python serial_monitor.py --port COM3 --no-restart`.

### Aggiornare la ricezione RF (revisione driver 2)

1. Apri `bsg.cmd` e scegli **6** per compilare con ESP-IDF locale.
2. Scegli **2** per flashare la nuova immagine, conservando configurazione e dati.
   Serve questo passaggio per correggere il driver nativo; la sola voce 3 non basta
   se la scheda ha ancora la revisione RF precedente.
3. Scegli **4** e controlla versione 0.2.0, pinout e messaggio di autoriconoscimento.
4. Collegati a **Bresser Gateway** e apri **http://192.168.4.1**.
5. Configura Wi-Fi, Wunderground, AMMS e MQTT/TLS nella prima sezione della dashboard.
   Abilita i servizi desiderati, salva e riconnettiti all'AP dopo il riavvio.

Cablaggio RFM95W-915S2: SCK18, MOSI23, MISO19, NSS27, RESET32,
DIO0 21, DIO1 33. Ricezione FSK **868,3 MHz**, anche se il nome del modulo
contiene 915. LED utente Wemos ESP32 mini GPIO2 (polarita configurabile).
Il nome commerciale 5-in-1 non garantisce la famiglia del protocollo: il riconoscimento verifica 5/6/7-in-1 con checksum.
Un errore RF segnala un frame corrotto o non supportato; la ricerca continua.
La lista dei protocolli e delle varianti supportate e nel [README](README.md).
Altre stazioni a 868 MHz non sono automaticamente compatibili.

Riferimenti: [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html)
e [comandi esptool](https://docs.espressif.com/projects/esptool/en/latest/esp32/esptool/basic-commands.html).

Il caricatore riprova fino a tre volte l'handshake REPL sulla stessa
connessione se il CP210x ha appena riavviato la scheda. Se un flash riesce
ma la copia Python fallisce, usare la voce 3 senza ripetere la cancellazione.

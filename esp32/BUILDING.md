# Compilazione del firmware

## Prerequisiti

La procedura consigliata usa Linux o WSL, perché è il percorso più semplice per la toolchain ESP-IDF impiegata dal port ESP32 di MicroPython.

Servono:

- Git;
- Python 3;
- toolchain richiesta dal port ESP32 di MicroPython;
- `esptool` o `mpremote` per installare il firmware.

Queste istruzioni sono predisposte per MicroPython `v1.29.0`.

Inizializzare prima la dipendenza AMMSUtils dalla radice del repository:

```sh
git submodule update --init --recursive
```

## 1. Recuperare MicroPython

Eseguire da una directory di lavoro esterna a questo repository:

```sh
git clone --branch v1.29.0 --depth 1 https://github.com/micropython/micropython.git
cd micropython
git submodule update --init lib/berkeley-db-1.xx lib/mbedtls lib/micropython-lib
make -C mpy-cross
```

Seguire inoltre la preparazione ufficiale del port ESP32 se la toolchain ESP-IDF non è già disponibile:

https://github.com/micropython/micropython/tree/master/ports/esp32

## 2. Compilare con il modulo Bresser

Impostare `BSG_MICROPY_DIR` al percorso assoluto della directory `BSG-Firmware-v2/esp32`.

```sh
cd ports/esp32
make submodules
make \
  BOARD=ESP32_GENERIC \
  FROZEN_MANIFEST="$BSG_MICROPY_DIR/manifest.py" \
  USER_C_MODULES="$BSG_MICROPY_DIR/native/micropython.cmake"
```

Il risultato si trova normalmente in:

```text
ports/esp32/build-ESP32_GENERIC/firmware.bin
```

La build usa l'ESP32 classico. Non selezionare una board ESP32-S3 per il Wemos D1 Mini32.

## 3. Installare

Individuare la porta seriale e cancellare/installare il firmware seguendo la guida ufficiale MicroPython. Un esempio, da adattare alla propria porta:

```sh
python -m esptool --chip esp32 --port /dev/ttyUSB0 erase_flash
python -m esptool --chip esp32 --port /dev/ttyUSB0 write_flash -z 0x1000 build-ESP32_GENERIC/firmware.bin
```

`boot.py`, `main.py` e i moduli applicativi sono congelati nell'immagine dal manifest. Il solo file da creare sulla flash della scheda è `/config.json`.

```sh
mpremote connect /dev/ttyUSB0 cp "$BSG_MICROPY_DIR/config.example.json" :config.json
```

Modificare prima la copia locale oppure usare il portale Web al primo avvio.

## 4. Test rapido dal REPL

Interrompere temporaneamente `main.py` con `Ctrl-C`, quindi:

```python
import bresser_native
print(bresser_native.status())
print(bresser_native.stats())
```

Il campo `chip_version` deve essere `18`, cioè `0x12`, per un SX1276/RFM95W riconosciuto.

Il trasmettitore Bresser 5-in-1 invia normalmente un messaggio a intervalli di alcuni secondi. Eseguire ripetutamente:

```python
print(bresser_native.poll())
```

## 5. Test host del decoder

Il decoder non dipende da ESP-IDF. Su una macchina con CMake e un compilatore C++:

```sh
cmake -S tests -B tests/build
cmake --build tests/build
ctest --test-dir tests/build --output-on-failure
```

## Diagnostica

- `RuntimeError: SX1276 init failed`: verificare alimentazione, massa, CS, RESET e bus SPI.
- `chip_version` diverso da `0x12`: il dispositivo non risponde correttamente via SPI o non è un SX1276 compatibile.
- `packets_seen` aumenta ma `packets_decoded` resta a zero: controllare frequenza, antenna, cablaggio e contatori `sync_errors`, `parity_errors`, `checksum_errors`.
- Nessun pacchetto: verificare che DIO0 sia collegato a GPIO21 e che il sensore trasmetta a 868,3 MHz.
- Errore TLS: verificare che l'orologio sia stato sincronizzato via NTP e che il server presenti una catena compatibile con ISRG Root X1.

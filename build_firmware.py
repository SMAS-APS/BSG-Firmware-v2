"""Build locale ESP-IDF/MicroPython, utilizzabile da qualsiasi IDE o terminale."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
VERSION = "v1.29.0"
CACHE = Path(os.environ.get("BSG_CACHE_DIR", str(Path.home() / ".cache/bsg-firmware")))
SOURCE = CACHE / ("micropython-" + VERSION)
BUILD = PROJECT / ".pio/build/esp32-wroom-32"


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def prepare():
    if not shutil.which("git"):
        raise RuntimeError("Installare Git e renderlo disponibile nel PATH.")
    if not (PROJECT / "external/AMMSUtils/amms/client.py").is_file():
        raise RuntimeError("AMMSUtils mancante: git submodule update --init --recursive")
    CACHE.mkdir(parents=True, exist_ok=True)
    if not (SOURCE / ".git").exists():
        run(["git", "clone", "--depth", "1", "--branch", VERSION,
             "https://github.com/micropython/micropython.git", SOURCE])
    tag = subprocess.check_output(["git", "-C", str(SOURCE), "describe", "--tags", "--exact-match"], text=True).strip()
    if tag != VERSION:
        raise RuntimeError("La cache MicroPython contiene una versione diversa da " + VERSION)
    run(["git", "-C", SOURCE, "submodule", "update", "--init", "--depth", "1",
         "lib/berkeley-db-1.xx", "lib/micropython-lib"])
    # Solo adattamenti ai comandi della build, nella cache esterna. Nessuna
    # modifica al driver Bresser, al decoder o alle funzionalita' MicroPython.
    rules = SOURCE / "py/mkrules.cmake"
    content = subprocess.check_output(["git", "-C", str(SOURCE), "show", "HEAD:py/mkrules.cmake"], text=True)
    content = content.replace("COMMAND touch ", "COMMAND ${CMAKE_COMMAND} -E touch ")
    helper = (PROJECT / "native/preprocess_qstr.py").as_posix()
    runner = (PROJECT / "native/run_qstr.py").as_posix()
    arguments = '''
function(bsg_write_qstr_args NAME)
    string(REPLACE ";" "\\n" CONTENT "${ARGN}")
    file(GENERATE OUTPUT "${MICROPY_GENHDR_DIR}/${NAME}" CONTENT "${CONTENT}\\n")
endfunction()
bsg_write_qstr_args(bsg_pp.txt pp ${CMAKE_C_COMPILER} -E output ${MICROPY_QSTRDEFS_LAST}
    cflags ${MICROPY_CPP_FLAGS} -DNO_QSTR cxxflags ${MICROPY_CPP_FLAGS} -DNO_QSTR
    sources ${MICROPY_SOURCE_QSTR})
bsg_write_qstr_args(bsg_preprocess.txt ${MICROPY_QSTRDEFS_PREPROCESSED} ${CMAKE_C_COMPILER}
    ${MICROPY_QSTRDEFS_PY} ${MICROPY_QSTRDEFS_PORT} ${MICROPY_QSTRDEFS_COLLECTED}
    -- ${MICROPY_CPP_FLAGS})
'''
    content = content.replace("# Generate qstrs\n", "# Generate qstrs\n" + arguments)
    lines = content.splitlines()
    replaced = 0
    for index, line in enumerate(lines):
        if "COMMAND cat ${MICROPY_QSTRDEFS_PY}" in line:
            lines[index] = ('    COMMAND ${Python3_EXECUTABLE} "' + helper + '" '
                            '--args-file ${MICROPY_GENHDR_DIR}/bsg_preprocess.txt')
            replaced += 1
        elif "COMMAND ${Python3_EXECUTABLE} ${MICROPY_PY_DIR}/makeqstrdefs.py pp " in line:
            lines[index] = ('    COMMAND ${Python3_EXECUTABLE} "' + runner + '" '
                            '${MICROPY_PY_DIR}/makeqstrdefs.py ${MICROPY_GENHDR_DIR}/bsg_pp.txt')
            replaced += 1
    if replaced != 2:
        raise RuntimeError("Pipeline QSTR MicroPython non riconosciuta")
    updated = "\n".join(lines) + "\n"
    if rules.read_text(encoding="utf-8") != updated:
        rules.write_text(updated, encoding="utf-8")
    print("Sorgenti pronti:", SOURCE)


def idf_environment(idf_path=None):
    selected = idf_path or os.environ.get("BSG_IDF_PATH") or os.environ.get("IDF_PATH")
    if not selected:
        default = Path.home() / ".espressif/bsg/esp-idf-v5.5.2"
        if (default / "tools/idf.py").is_file():
            selected = str(default)
    if not selected or not (Path(selected) / "tools/idf.py").is_file():
        raise RuntimeError("ESP-IDF mancante: installare v5.5.2, aprire ESP-IDF Terminal oppure impostare BSG_IDF_PATH. Vedere README.md.")
    sdk = Path(selected).resolve()
    env = os.environ.copy()
    env["IDF_PATH"] = str(sdk)
    result = run([sys.executable, sdk / "tools/idf_tools.py", "export", "--format", "key-value"],
                 env=env, text=True, stdout=subprocess.PIPE)
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            for name in ("PATH", "IDF_PATH", "IDF_TOOLS_PATH"):
                value = value.replace("${" + name + "}", env.get(name, ""))
                value = value.replace("$" + name, env.get(name, ""))
                value = value.replace("%" + name + "%", env.get(name, ""))
            env[key] = value
    python_dir = Path(env.get("IDF_PYTHON_ENV_PATH", ""))
    python = python_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise RuntimeError("Python ESP-IDF non disponibile: eseguire install.bat esp32 (Windows) o install.sh esp32 (Linux/macOS).")
    cross = run([python, "-c", "import mpy_cross; print(mpy_cross.mpy_cross)"],
                text=True, stdout=subprocess.PIPE, env=env).stdout.strip()
    cross_version = run([cross, "--version"], text=True, stdout=subprocess.PIPE).stdout
    if "v1.29.0" not in cross_version:
        raise RuntimeError("Installare mpy-cross==1.29.0.post2 nel Python ESP-IDF")
    env["MICROPY_MPYCROSS"] = cross
    env["PATH"] = str(python.parent) + os.pathsep + env["PATH"]
    return sdk, python, env


def idf_command(sdk, python, env, actions, port=None):
    args = [python, sdk / "tools/idf.py", "-B", BUILD,
            "-D", "MICROPY_BOARD=ESP32_GENERIC",
            "-D", "MICROPY_FROZEN_MANIFEST=" + (PROJECT / "manifest.py").as_posix(),
            "-D", "USER_C_MODULES=" + (PROJECT / "native/micropython.cmake").as_posix()]
    if port:
        args += ["-p", port]
    run(args + actions, cwd=SOURCE / "ports/esp32", env=env)


def build(sdk, python, env):
    prepare()
    idf_command(sdk, python, env, ["build"])
    run([python, SOURCE / "ports/esp32/makeimg.py", BUILD / "sdkconfig",
         BUILD / "bootloader/bootloader.bin", BUILD / "partition_table/partition-table.bin",
         BUILD / "micropython.bin", BUILD / "firmware.bin", BUILD / "micropython.uf2"], env=env)
    image = BUILD / "firmware.bin"
    metadata = {"schema": 2, "chip": "esp32", "board": "ESP32-WROOM-32",
                "micropython": VERSION, "native_modules": ["bresser_native"],
                "flash_offset": 4096,
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    image.with_suffix(".bin.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print("Firmware MicroPython + Bresser:", BUILD / "firmware.bin")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "doctor", "build", "flash", "monitor"])
    parser.add_argument("--idf-path", help="Percorso ESP-IDF installato")
    parser.add_argument("--port", help="Porta seriale, per esempio COM5 o /dev/ttyUSB0")
    args = parser.parse_args(argv)
    if args.action == "prepare":
        prepare()
        return
    sdk, python, env = idf_environment(args.idf_path)
    if args.action == "doctor":
        print("ESP-IDF:", sdk)
        print("Python:", python)
        print("mpy-cross:", env["MICROPY_MPYCROSS"])
        return
    if args.action in ("flash", "monitor"):
        if not args.port:
            raise RuntimeError("Specificare --port COM5 (o la porta effettiva della scheda)")
    if args.action in ("build", "flash"):
        build(sdk, python, env)
    if args.action in ("flash", "monitor"):
        if args.action == "flash":
            # Caricare anche gli script evita che vecchi file nel filesystem
            # continuino a prevalere sull'applicazione della nuova immagine.
            run([python, PROJECT / "bsg.py", "flash", "--port", args.port], env=env)
        else:
            idf_command(sdk, python, env, ["monitor"], args.port)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print("Errore:", error, file=sys.stderr)
        sys.exit(1)

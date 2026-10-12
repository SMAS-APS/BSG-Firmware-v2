"""Pulsanti PlatformIO collegati alla stessa build ESP-IDF usata da ogni IDE."""
import subprocess
from pathlib import Path
from SCons.Script import AlwaysBuild, Default, DefaultEnvironment

env = DefaultEnvironment()
script = Path(env.subst("$BUILD_SCRIPT")).resolve().parents[1] / "build_firmware.py"


def build(source, target, env):
    subprocess.run([env.subst("$PYTHONEXE"), str(script), "build"], check=True)


def upload(source, target, env):
    env.AutodetectUploadPort()
    subprocess.run([env.subst("$PYTHONEXE"), str(script), "flash",
                    "--port", env.subst("$UPLOAD_PORT")], check=True)


node = env.Alias("buildprog", [], build)
AlwaysBuild(node)
# build_firmware.py flash compila gia': non ripetere la stessa build nel grafo.
flash = env.Alias("upload", [], upload)
AlwaysBuild(flash)
Default(node)

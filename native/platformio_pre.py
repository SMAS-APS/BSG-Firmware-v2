from pathlib import Path

Import("env")
env.Replace(BUILD_SCRIPT=str(Path(env.subst("$PROJECT_SRC_DIR")) / "platformio_builder.py"))

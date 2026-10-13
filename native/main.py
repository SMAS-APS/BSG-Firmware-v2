"""Avvio congelato: delega al loader A/B, con fallback applicativo legacy."""
import json
import os

ota_ready = False
try:
    os.stat("/ota-state.json")
    with open("/ota-state.json") as state_file:
        ota_ready = json.load(state_file).get("schema") == 1
except (OSError, ValueError, TypeError):
    pass

if ota_ready:
    from ota_boot import boot
    boot()
else:
    try:
        script = open("/main.py")
    except OSError:
        from main_app import run
        run()
    else:
        with script:
            source = script.read()
        exec(source, globals())

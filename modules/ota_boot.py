"""Loader A/B stabile, congelato nel firmware MicroPython BSG."""
import json
import os
import sys


STATE_PATH = "/ota-state.json"
OTA_ROOT = "/ota"
SLOTS = ("a", "b")


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _replace(source, target):
    getattr(os, "replace", os.rename)(source, target)


def load_state():
    try:
        with open(STATE_PATH) as stream:
            state = json.load(stream)
        if state.get("schema") != 1 or state.get("active") not in SLOTS:
            raise ValueError("stato OTA non valido")
        return state
    except (OSError, ValueError, TypeError):
        return {"schema": 1, "active": "a", "previous": None, "pending": None,
                "attempts": 0, "version": None, "last_result": "bootstrap"}


def save_state(state):
    temporary = STATE_PATH + ".tmp"
    with open(temporary, "w") as stream:
        json.dump(state, stream)
    _replace(temporary, STATE_PATH)


def stage(slot, version, job_id):
    if slot not in SLOTS or not _exists("%s/%s/main.py" % (OTA_ROOT, slot)):
        raise ValueError("slot OTA non avviabile")
    state = load_state()
    versions = state.get("versions", {})
    versions[slot] = version
    state.update(previous=state.get("active"), active=slot, pending=slot, attempts=0,
                 version=version, job_id=job_id, last_result="pending")
    state["versions"] = versions
    save_state(state)


def confirm():
    state = load_state()
    if not state.get("pending"):
        return False
    state["report_pending"] = {"job_id": state.get("job_id"), "status": "success",
                               "installed_version": state.get("version")}
    state.update(previous=None, pending=None, attempts=0, job_id=None,
                 last_result="success")
    save_state(state)
    return True


def rollback(reason):
    state = load_state()
    previous = state.get("previous")
    if previous in SLOTS and _exists("%s/%s/main.py" % (OTA_ROOT, previous)):
        state["active"] = previous
    job_id = state.get("job_id")
    versions = state.get("versions", {})
    state["report_pending"] = {"job_id": job_id, "status": "rolled_back",
                               "installed_version": versions.get(state.get("active")),
                               "error": str(reason)[:160]}
    state.update(previous=None, pending=None, attempts=0, job_id=None,
                 last_result="rolled_back", last_error=str(reason)[:160])
    save_state(state)


def _execute(path):
    slot_root = path.rsplit("/", 1)[0]
    for item in (slot_root + "/lib", slot_root + "/modules", slot_root):
        if item in sys.path:
            sys.path.remove(item)
        sys.path.insert(0, item)
    with open(path) as stream:
        source = stream.read()
    exec(source, {"__name__": "__main__", "__file__": path})


def boot():
    state = load_state()
    slot = state.get("pending") or state.get("active")
    if state.get("pending"):
        state["attempts"] = int(state.get("attempts", 0)) + 1
        if state["attempts"] > 2:
            rollback("conferma salute assente dopo due avvii")
            state = load_state()
            slot = state["active"]
        else:
            save_state(state)  # prima di eseguire codice aggiornabile
    path = "%s/%s/main.py" % (OTA_ROOT, slot)
    if not _exists(path):
        path = "/main.py" if _exists("/main.py") else None
    if path:
        try:
            _execute(path)
            return
        except Exception as exc:
            if state.get("pending"):
                rollback("eccezione boot: %s" % type(exc).__name__)
                import machine
                machine.reset()
            raise
    from main_app import run
    run()

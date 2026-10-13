"""Conferma salute della release BSG in attesa."""
import time

from ota_boot import confirm, load_state, save_state


_health = {"radio": False, "network": False, "amms": False}
_guard_started = False
_guard_deadline = None
_reporter = None


def status():
    state = load_state()
    return {
        "slot": state.get("active"), "pending": bool(state.get("pending")),
        "attempts": state.get("attempts", 0), "last_result": state.get("last_result"),
        "last_error": state.get("last_error", ""), "health": _health.copy(),
    }


def mark(component):
    if component in _health:
        _health[component] = True
    if all(_health.values()):
        confirm()
        _flush_report()


def initialize_version(version):
    state = load_state()
    versions = state.get("versions", {})
    if versions.get(state.get("active")) != version and not state.get("pending"):
        versions[state.get("active")] = version
        state["versions"] = versions
        state["version"] = version
        try:
            save_state(state)
        except OSError:
            pass


def set_reporter(reporter):
    global _reporter
    _reporter = reporter
    _flush_report()


def start_updater(config):
    # Avoid importing the HTTPS/TLS client and certificates when OTA is off.
    amms = config.get("amms", {})
    updates = config.get("updates", {})
    endpoint = updates.get("server_url") or amms.get("url", "")
    if not (updates.get("enabled", True) and amms.get("enabled")
            and endpoint.startswith("https://")
            and amms.get("auth_mode") == "hmac-sha256"
            and amms.get("station_id") and amms.get("key_id")
            and len(amms.get("secret_hex", "")) == 64):
        set_reporter(None)
        return None
    from ota_update import OTAUpdater
    updater = OTAUpdater(config)
    set_reporter(updater.report_boot_result)
    updater.start()
    return updater


def _flush_report():
    state = load_state()
    report = state.get("report_pending")
    if not report or not _reporter or not report.get("job_id"):
        return
    try:
        if _reporter(report):
            state = load_state()
            state.pop("report_pending", None)
            save_state(state)
    except Exception:
        pass


def start_guard(timeout_seconds=300):
    global _guard_started, _guard_deadline
    if _guard_started or not load_state().get("pending"):
        return
    _guard_started = True
    _guard_deadline = time.ticks_add(time.ticks_ms(), int(timeout_seconds) * 1000)


def tick(now=None):
    if _guard_deadline is None:
        return
    now = time.ticks_ms() if now is None else now
    if time.ticks_diff(now, _guard_deadline) >= 0 and load_state().get("pending"):
        import machine
        machine.reset()

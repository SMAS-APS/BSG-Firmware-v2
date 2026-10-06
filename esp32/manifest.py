include("$(PORT_DIR)/boards/manifest.py")
require("ntptime")

freeze("modules", (
    "amms.py",
    "ca_cert.py",
    "config_store.py",
    "main_app.py",
    "secure_http.py",
    "wifi_manager.py",
))

freeze(".", (
    "boot.py",
    "main.py",
))

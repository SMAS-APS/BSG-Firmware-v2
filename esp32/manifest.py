include("$(PORT_DIR)/boards/manifest.py")
require("ntptime")

freeze("modules", (
    "config_store.py",
    "main_app.py",
    "wifi_manager.py",
))

freeze("../external/AMMSUtils", (
    "amms/__init__.py",
    "amms/auth.py",
    "amms/client.py",
    "amms/credentials.py",
    "amms/payload.py",
    "amms/transports/__init__.py",
    "amms/transports/ca_cert.py",
    "amms/transports/micropython_http.py",
))

freeze(".", (
    "boot.py",
    "main.py",
))

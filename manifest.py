include("$(PORT_DIR)/boards/manifest.py")
require("ntptime")
require("umqtt.simple")

freeze("modules", (
    "bsg_runtime.py",
    "bresser_protocols.py",
    "rx_led.py",
    "ap_uplink.py",
    "config_store.py",
    "main_app.py",
    "mqtt_transport.py",
    "wu_support.py",
    "wifi_manager.py",
))

freeze("external/AMMSUtils", (
    "amms/__init__.py",
    "amms/auth.py",
    "amms/client.py",
    "amms/credentials.py",
    "amms/payload.py",
    "amms/mqtt.py",
    "amms/weather_underground.py",
    "amms/transports/__init__.py",
    "amms/transports/ca_cert.py",
    "amms/transports/micropython_http.py",
))

# Avvio congelato che permette agli script nel filesystem di essere aggiornati
# via USB senza ricompilare l'interprete o la libreria Bresser.
freeze("native", (
    "boot.py",
    "main.py",
))

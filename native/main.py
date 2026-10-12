"""Avvio congelato: esegue /main.py, altrimenti l'applicazione inclusa."""
try:
    script = open("/main.py")
except OSError:
    from main_app import run
    run()
else:
    with script:
        source = script.read()
    exec(source, globals())

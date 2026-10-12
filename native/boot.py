"""Avvio congelato: i moduli nel filesystem hanno precedenza sui frozen."""
import gc
import sys

for path in ("/lib", "/"):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

try:
    script = open("/boot.py")
except OSError:
    gc.collect()
    if hasattr(gc, "threshold"):
        gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
else:
    with script:
        source = script.read()
    exec(source, globals())

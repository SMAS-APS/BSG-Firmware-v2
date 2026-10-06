import gc


# Riduce la probabilita' che una raccolta completa cada durante la gestione
# di un pacchetto radio. Il pacchetto e' comunque conservato nel FIFO SX1276.
gc.collect()
if hasattr(gc, "threshold"):
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

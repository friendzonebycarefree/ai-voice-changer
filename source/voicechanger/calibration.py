"""Find a sustainable stream block before opening the microphone."""
import math

MAX_BLOCK_MS = 400

def calibrate(backend, cancelled, progress):
    if cancelled.is_set():return None
    elapsed = backend.warmup()
    for _ in range(6):
        if cancelled.is_set():
            return None
        block = backend.chunk / 16
        if elapsed <= block * .85:
            return block
        if block >= MAX_BLOCK_MS:
            progress('Обработка медленнее реального времени. Продолжаю с задержкой.')
            return block
        adjusted = min(MAX_BLOCK_MS, max(block + 20, math.ceil(elapsed * 1.3 / 20) * 20))
        progress('Подстраиваю задержку под скорость компьютера…')
        backend.configure_stream(adjusted)
        elapsed = backend.warmup()
    progress('Продолжаю с увеличенной задержкой.')
    return backend.chunk / 16

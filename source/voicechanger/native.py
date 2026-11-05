"""C ABI bridge to the C++20 WASAPI engine (no Python audio callback)."""
import ctypes as C
from pathlib import Path
import numpy as np


class NativeAudio:
    def __init__(self, dll_path: Path):
        self.dll = C.CDLL(str(dll_path))
        d = self.dll
        pointer = C.POINTER(C.c_float)
        d.vc_devices.argtypes = [C.c_wchar_p, C.c_int]
        d.vc_devices.restype = C.c_int
        d.vc_open.argtypes = [C.c_int, C.c_wchar_p, C.POINTER(C.c_long)]
        d.vc_open.restype = C.c_void_p
        d.vc_close.argtypes = [C.c_void_p]
        d.vc_read.argtypes = [C.c_void_p, pointer, C.c_int]
        d.vc_read.restype = C.c_int
        d.vc_write.argtypes = [C.c_void_p, pointer, C.c_int]
        d.vc_mute.argtypes = [C.c_void_p, C.c_int]
        d.vc_flush.argtypes = [C.c_void_p]
        d.vc_stats.argtypes = [C.c_void_p, C.POINTER(C.c_double)]

    def devices(self):
        buffer = C.create_unicode_buffer(65536)
        result = self.dll.vc_devices(buffer, len(buffer))
        if result < 0:
            raise RuntimeError('Не удалось получить устройства WASAPI')
        return [dict(zip(('flow', 'id', 'name'), line.split('\t', 2)))
                for line in buffer.value.splitlines() if line]

    def open(self, capture, device_id):
        error = C.c_long()
        handle = self.dll.vc_open(int(capture), device_id, C.byref(error))
        if not handle:
            raise RuntimeError(f'Не удалось открыть устройство WASAPI: 0x{error.value & 0xffffffff:08X}')
        return Stream(self.dll, handle)


class Stream:
    def __init__(self, dll, handle):
        self.dll, self.handle = dll, handle

    def read(self, buffer):
        return self.dll.vc_read(self.handle, buffer.ctypes.data_as(C.POINTER(C.c_float)), len(buffer))

    def write(self, buffer):
        buffer = np.ascontiguousarray(buffer, dtype=np.float32)
        self.dll.vc_write(self.handle, buffer.ctypes.data_as(C.POINTER(C.c_float)), len(buffer))

    def stats(self):
        values = (C.c_double * 7)()
        self.dll.vc_stats(self.handle, values)
        names = ('queued_samples', 'dropped_samples', 'silence_samples', 'error', 'device_latency_ms', 'peak', 'discontinuities')
        return dict(zip(names, values))

    def mute(self, muted):
        self.dll.vc_mute(self.handle, int(muted))

    def flush(self):
        self.dll.vc_flush(self.handle)

    def close(self):
        if self.handle:
            self.dll.vc_close(self.handle)
            self.handle = None


def virtual_output(device):
    return device['flow'] == 'render' and any(
        tag in device['name'].lower() for tag in ('cable input', 'voicemeeter input', 'vb-audio'))

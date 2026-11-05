from pathlib import Path
import sys


def application_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def native_path():
    root = application_root()
    return root / ('audio_engine.dll' if getattr(sys, 'frozen', False) else 'source/native/audio_engine.dll')

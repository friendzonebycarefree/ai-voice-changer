from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path

# Presets set the actual block/context and diffusion-step tradeoff.
MODES = {'Low Latency': 80, 'Balanced': 120, 'High Quality': 180}
PROFILES = {'Natural Female': (0.0, 1.0), 'Soft Female': (0.4, 0.9)}


def user_dir():
    path = Path(os.environ.get('LOCALAPPDATA', str(Path.cwd()))) / 'LocalVoiceChanger'
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    microphone: str = ''
    output: str = ''
    headphones: str = ''
    mode: str = 'Balanced'
    profile: str = 'Natural Female'
    volume: float = 1.0
    softness: float = 0.0
    noise_gate_db: float = -60.0
    threads: int = 4
    backend: str = 'auto'
    model: str = 'seed'
    auto_pitch: bool = True
    pitch: float = 0.0
    target_low: float = 165.0
    target_high: float = 320.0

    def validate(self):
        if self.mode not in MODES or self.backend not in ('auto', 'cpu', 'cuda'):
            raise ValueError('Неизвестный режим или backend')
        if not (0 <= self.volume <= 2 and 0 <= self.softness <= 1 and -90 <= self.noise_gate_db <= -25):
            raise ValueError('Настройки голоса вне допустимых пределов')
        if not (1 <= self.threads <= 16):
            raise ValueError('Недопустимое число потоков')
        if self.model not in ('seed','rvc') or not (-12<=self.pitch<=12 and 80<=self.target_low<self.target_high<=600):
            raise ValueError('Недопустимая модель или диапазон F0')
        return self

    @classmethod
    def load(cls, path=None):
        path = path or user_dir() / 'settings.json'
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding='utf-8'))
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed}).validate()

    def save(self, path=None):
        self.validate()
        path = path or user_dir() / 'settings.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)

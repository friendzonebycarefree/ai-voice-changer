"""Adaptive F0 conditioning for the RVC backend; never a waveform pitch effect."""
from collections import deque
import numpy as np


class AdaptivePitchMapper:
    def __init__(self, auto=True, semitones=0, low_hz=165, high_hz=320):
        if not (80 <= low_hz < high_hz <= 600 and -12 <= semitones <= 12):
            raise ValueError('Недопустимый целевой диапазон F0')
        self.auto, self.semitones = bool(auto), float(semitones)
        self.low, self.high = float(low_hz), float(high_hz)
        self.history = deque(maxlen=400)
        self.log_center = None

    def reset(self):
        self.history.clear(); self.log_center = None

    def map(self, f0, new_slice=None):
        f0 = np.asarray(f0, dtype=np.float64)
        if f0.ndim != 1 or not np.isfinite(f0).all() or (f0 < 0).any():
            raise ValueError('Некорректный контур F0')
        fresh = f0 if new_slice is None else f0[new_slice]
        fresh = fresh[(fresh >= 50) & (fresh <= 1100)]
        self.history.extend(np.log(fresh).tolist())
        voiced = f0 >= 50
        output = np.zeros_like(f0)
        if not voiced.any(): return output.astype(np.float32)
        shift = self.semitones*np.log(2)/12
        if self.auto:
            samples = np.array(self.history) if self.history else np.log(f0[voiced])
            observed = float(np.median(samples))
            self.log_center = observed if self.log_center is None else .95*self.log_center + .05*observed
            target = .5*(np.log(self.low)+np.log(self.high))
            span = float(np.percentile(samples,90)-np.percentile(samples,10)) if len(samples)>8 else 0
            # Limited stretch preserves contour direction and expressiveness.
            stretch = np.clip(np.log(self.high/self.low)/span,.85,1.15) if span>.05 else 1.
            values = target + (np.log(f0[voiced])-self.log_center)*stretch + shift
        else:
            values = np.log(f0[voiced]) + shift
        output[voiced] = np.clip(np.exp(values),50,1100)
        return output.astype(np.float32)


def coarse_f0(f0):
    mel = 1127*np.log1p(np.asarray(f0)/700)
    low, high = 1127*np.log1p(50/700), 1127*np.log1p(1100/700)
    return np.clip(np.rint((mel-low)*254/(high-low)+1),1,255).astype(np.int64)

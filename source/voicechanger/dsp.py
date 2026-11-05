"""Conservative DSP used around the actual neural converter."""
import numpy as np
from scipy.signal import butter, sosfilt


class VoiceDSP:
    def __init__(self, softness=0.0, volume=1.0, gate_db=-60, output_rate=16000):
        self.softness, self.volume = softness, volume
        self.gate = 10 ** (gate_db / 20)
        self.highpass = butter(2, 65, fs=16000, btype='highpass', output='sos')
        self.target_softness,self.target_volume=softness,volume
        self.lowpass = butter(2, 4000, fs=output_rate, btype='lowpass', output='sos')
        self.hpstate = np.zeros((len(self.highpass), 2))
        self.lpstate = np.zeros((len(self.lowpass), 2))
        self.envelope = 1.0

    def set_voice(self,cfg):
        self.target_softness,self.target_volume=cfg.softness,cfg.volume
        self.gate=10**(cfg.noise_gate_db/20)

    def preprocess(self, x):
        y, self.hpstate = sosfilt(self.highpass, np.clip(x, -1, 1), zi=self.hpstate)
        # Smooth attenuator rather than hard VAD: preserves quiet consonants.
        rms = float(np.sqrt(np.mean(y*y) + 1e-12))
        target = min(1.0, max(0.05, rms / self.gate))
        tau=.002 if target>self.envelope else .15
        envelope=target+(self.envelope-target)*np.exp(-np.arange(1,len(y)+1)/(tau*16000))
        self.envelope=float(envelope[-1]) if len(y) else self.envelope
        return (y * envelope).astype(np.float32)

    def postprocess(self, x):
        low, self.lpstate = sosfilt(self.lowpass, x, zi=self.lpstate)
        soft=np.linspace(self.softness,self.target_softness,len(x))
        volume=np.linspace(self.volume,self.target_volume,len(x))
        y = ((1-soft)*x + soft*low) * volume
        self.softness,self.volume=self.target_softness,self.target_volume
        # Transparent below 0.95; soft limiting near full scale, no dry mix.
        absolute = np.abs(y)
        y = np.where(absolute <= .95, y,
                     np.sign(y) * (.95 + .05*np.tanh((absolute-.95)/.05)))
        return y.astype(np.float32)

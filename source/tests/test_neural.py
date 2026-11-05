import unittest
import numpy as np
import soundfile as sf
from voicechanger.config import Settings
from voicechanger.neural import load_backend
from voicechanger.paths import application_root

class NeuralIntegrationTests(unittest.TestCase):
    def test_real_seed_forward_and_sola_on_real_speech(self):
        backend=load_backend(Settings(model='seed',backend='cpu',mode='Low Latency'))
        try:
            speech,sr=sf.read(application_root()/'samples/ru-original.wav',dtype='float32',always_2d=True)
            self.assertEqual(sr,16000);speech=speech.mean(axis=1)
            blocks=speech[:len(speech)//backend.chunk*backend.chunk].reshape(-1,backend.chunk)
            index=int(np.argmax(np.mean(blocks*blocks,axis=1)))
            outputs=[]
            for block in blocks[max(0,index-1):index+1]:
                output,elapsed=backend.process(block);outputs.append(output)
                self.assertEqual(len(output),round(backend.chunk*backend.output_rate/16000))
                self.assertTrue(np.isfinite(output).all());self.assertGreater(elapsed,0)
            self.assertGreater(np.max(abs(np.concatenate(outputs))),.001)
            backend.reset()
            with self.assertRaises(ValueError):backend.process(np.full(backend.chunk,np.nan,np.float32))
        finally:backend.close()

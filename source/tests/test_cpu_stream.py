import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from voicechanger.engine import AudioWorker
from voicechanger.config import Settings

class CPUStreamTests(unittest.TestCase):
    def test_cpu_stream_renders_and_reports_without_cuda_calls(self):
        worker=AudioWorker(Settings(microphone='mic',output='ears',backend='cpu'))
        class Backend:
            chunk=1920;output_rate=22050;params={'resampler':'LQ'};name='CPU fixture';last_timings={};calls=0
            def warmup(self):return 1
            def reset(self):pass
            def close(self):pass
            def process(self,x):
                self.calls+=1;time.sleep(.022)
                if self.calls==12:worker.stop()
                return np.zeros(2646,np.float32),193
        class Endpoint:
            handle=True;writes=0
            def stats(self):return dict(queued_samples=0,dropped_samples=0,silence_samples=0,error=0,device_latency_ms=0,peak=.1,discontinuities=0)
            def read(self,x):x[:]=.1;return len(x)
            def write(self,x):self.writes+=1
            def mute(self,value):pass
            def flush(self):pass
            def close(self):self.handle=False
        capture,output=Endpoint(),Endpoint();backend=Backend()
        class Native:
            def __init__(self,*args):pass
            def devices(self):return [dict(id='mic',flow='capture',name='Mic'),dict(id='ears',flow='render',name='Headphones')]
            def open(self,capture_flag,device):return capture if capture_flag else output
        failures=[];metrics=[];worker.failure.connect(failures.append);worker.metrics.connect(metrics.append)
        with tempfile.TemporaryDirectory() as folder:
            with patch('voicechanger.engine.torch.cuda.is_available',return_value=False),patch('voicechanger.engine.torch.cuda.memory_allocated',side_effect=AssertionError('CUDA used')),patch('voicechanger.engine.NativeAudio',Native),patch('voicechanger.engine.load_backend',return_value=backend),patch('voicechanger.engine.user_dir',lambda:Path(folder)):
                worker.run()
        self.assertEqual(failures,[]);self.assertGreaterEqual(output.writes,8)
        self.assertTrue(metrics);self.assertEqual(metrics[0]['gpu_allocated_mib'],0)
        self.assertFalse(capture.handle);self.assertFalse(output.handle)

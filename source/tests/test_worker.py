import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QCoreApplication
from voicechanger.engine import AudioWorker
from voicechanger.config import Settings

class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])

    def test_cpu_can_reach_model_loading_without_opening_capture(self):
        worker=AudioWorker(Settings(microphone='mic',output='ears'));failures=[];worker.failure.connect(failures.append)
        class Devices:
            def __init__(self,*args):pass
            def devices(self):return [dict(id='mic',flow='capture',name='Mic'),dict(id='ears',flow='render',name='Headphones')]
            def open(self,*args):raise AssertionError('Capture should wait for model load')
        with tempfile.TemporaryDirectory() as folder:
            with patch('voicechanger.engine.torch.cuda.is_available',return_value=False),patch('voicechanger.engine.NativeAudio',Devices),patch('voicechanger.engine.load_backend',side_effect=RuntimeError('Reached CPU model load')) as load,patch('voicechanger.engine.user_dir',lambda:Path(folder)):
                worker.run();load.assert_called_once()
        self.assertEqual(failures,['Reached CPU model load'])

    def test_model_failure_mutes_and_closes_without_source_passthrough(self):
        worker=AudioWorker(Settings(microphone='mic',output='cable'))
        class Fault:
            chunk=1920;output_rate=22050;params={'resampler':'LQ'};name='Fault';last_timings={}
            def warmup(self):return 1
            def reset(self):pass
            def process(self,x):raise RuntimeError('Injected inference failure')
            def close(self):pass
        class Endpoint:
            handle=True;muted=False;writes=0
            def stats(self):return dict(queued_samples=0,dropped_samples=0,silence_samples=0,error=0,device_latency_ms=0,peak=.1,discontinuities=0)
            def read(self,x):x[:]=.1;return len(x)
            def write(self,x):self.writes+=1
            def mute(self,value):self.muted=value
            def flush(self):pass
            def close(self):self.handle=False
        capture,output=Endpoint(),Endpoint()
        class Devices:
            def __init__(self,*_):pass
            def devices(self):return [dict(flow='capture',id='mic',name='Mic'),dict(flow='render',id='cable',name='CABLE Input')]
            def open(self,is_capture,device_id):return capture if is_capture else output
        failures=[];worker.failure.connect(failures.append)
        with tempfile.TemporaryDirectory() as folder:
            with patch('voicechanger.engine.NativeAudio',Devices),patch('voicechanger.engine.load_backend',return_value=Fault()),patch('voicechanger.engine.torch.cuda.is_available',return_value=True),patch('voicechanger.engine.user_dir',lambda:Path(folder)):
                worker.run()
        self.assertEqual(failures,['Injected inference failure']);self.assertTrue(output.muted)
        self.assertEqual(output.writes,0);self.assertFalse(output.handle);self.assertFalse(capture.handle)

    def test_voice_update_cannot_switch_running_model_or_device(self):
        worker=AudioWorker(Settings(model='seed',microphone='original'))
        worker.update_voice(Settings(model='rvc',microphone='different',volume=.7,softness=.4))
        self.assertEqual(worker._pending_voice.model,'seed');self.assertEqual(worker._pending_voice.microphone,'original')
        self.assertEqual(worker._pending_voice.volume,.7)

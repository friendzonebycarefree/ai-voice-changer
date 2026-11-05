import tempfile,unittest,shutil
from pathlib import Path
import numpy as np
from voicechanger.config import Settings
from voicechanger.assets import ModelStore
from voicechanger.dsp import VoiceDSP
from voicechanger.native import NativeAudio
from voicechanger.paths import application_root,native_path

class CoreTests(unittest.TestCase):
    def test_settings_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';cfg=Settings(volume=.8,softness=.35,model='rvc',pitch=3)
            cfg.save(path);self.assertEqual(cfg,Settings.load(path))
            path.write_text('{"volume":99}',encoding='utf-8')
            with self.assertRaises(ValueError):Settings.load(path)
        with self.assertRaises(ValueError):Settings(target_low=400,target_high=200).validate()

    def test_dsp_silence_and_limiter(self):
        dsp=VoiceDSP(.4,2,-60,22050)
        self.assertTrue(np.all(dsp.preprocess(np.zeros(1280,np.float32))==0))
        result=dsp.postprocess(np.ones(1764,np.float32)*4)
        self.assertTrue(np.isfinite(result).all());self.assertLessEqual(np.max(abs(result)),1)

    def test_manifest_and_asset_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'manifest.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'Манифест'):ModelStore(root)
            shutil.copy2(application_root()/'models/manifest.json',root/'manifest.json')
            store=ModelStore(root);meta=store.assets['female.reference'];path=root/meta['path'];path.parent.mkdir(parents=True)
            original=(application_root()/'models'/meta['path']).read_bytes();altered=bytearray(original);altered[100]^=1;path.write_bytes(altered)
            with self.assertRaisesRegex(ValueError,'сумма'):store.path('female.reference')

    def test_native_device_enumeration_and_bounded_silent_render(self):
        native=NativeAudio(native_path());devices=native.devices()
        self.assertTrue(all(d['flow'] in ('capture','render') for d in devices))
        render=[d for d in devices if d['flow']=='render']
        if not render:self.skipTest('No render endpoint')
        stream=native.open(False,render[0]['id'])
        try:
            stream.write(np.zeros(48000,np.float32));stats=stream.stats()
            self.assertLessEqual(stats['queued_samples'],28800);self.assertGreater(stats['dropped_samples'],0)
            stream.mute(True);self.assertEqual(stream.stats()['queued_samples'],0)
        finally:stream.close()


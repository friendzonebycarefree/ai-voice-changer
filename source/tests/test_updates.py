import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from voicechanger.updates import inspect_patch,install_patch

def bundle(path,files,bad=False):
    manifest={'version':'0.3.0','files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('_update.json',json.dumps(manifest))
        for k,v in files.items():z.writestr('payload/'+k,v if not bad else b'corrupt')

class UpdateTests(unittest.TestCase):
    def test_install_keeps_models_and_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);z=root/'update.zip';bundle(z,{'app/source/main.py':b'new'})
            model=root/'app/models/voice.bin';model.parent.mkdir(parents=True);model.write_bytes(b'keep')
            self.assertEqual(install_patch(z,root),'0.3.0');self.assertEqual(model.read_bytes(),b'keep')
            self.assertEqual((root/'app/source/main.py').read_bytes(),b'new')
    def test_checksum_rejected_before_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);z=root/'update.zip';bundle(z,{'app/source/main.py':b'new'},True)
            with self.assertRaises(ValueError):install_patch(z,root)
            self.assertFalse((root/'app/source/main.py').exists())
    def test_traversal_and_model_changes_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('../escape','app/source/../../../escape','app/models/voice.bin'):
                z=Path(folder)/'update.zip';bundle(z,{name:b'bad'})
                with self.assertRaises(ValueError):inspect_patch(z)
    def test_failed_second_replace_rolls_back_first_file(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'app/source/a.py';p.parent.mkdir(parents=True);p.write_bytes(b'old')
            z=root/'update.zip';bundle(z,{'app/source/a.py':b'new','app/source/b.py':b'new'})
            original=os.replace;calls=[]
            def replace(a,b):
                calls.append(b)
                if len(calls)==2:raise OSError('Injected locked file')
                return original(a,b)
            with patch('voicechanger.updates.os.replace',side_effect=replace):
                with self.assertRaises(OSError):install_patch(z,root)
            self.assertEqual(p.read_bytes(),b'old');self.assertFalse((root/'app/source/b.py').exists())

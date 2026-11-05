from pathlib import Path
import hashlib
import json
from .paths import application_root

MANIFEST_SHA256='a5740cb3ab6732f8f029780fe225b238e06e9169067b260b417944c9f422fb07'


class ModelStore:
    def __init__(self,root=None):
        self.root=(Path(root) if root else application_root()/'models').resolve()
        data=(self.root/'manifest.json').read_bytes()
        if hashlib.sha256(data).hexdigest()!=MANIFEST_SHA256:
            raise ValueError('Манифест моделей изменён. Загрузка запрещена.')
        self.assets=json.loads(data)['assets']
        self.verified=set()

    def path(self,key):
        meta=self.assets[key]
        path=(self.root/meta['path']).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Путь модели вне каталога приложения')
        if key not in self.verified:
            if path.stat().st_size!=meta['size']:
                raise ValueError(f'Размер компонента {key} не совпадает с проверенным')
            with path.open('rb') as source:
                digest=hashlib.file_digest(source,'sha256').hexdigest()
            if digest!=meta['sha256']:
                raise ValueError(f'Контрольная сумма {key} не совпадает. Загрузка запрещена.')
            self.verified.add(key)
        return path

    def verify(self,keys):
        for key in keys:self.path(key)

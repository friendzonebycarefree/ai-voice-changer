"""Small transactional code updates. Model/runtime directories are never changed."""
import hashlib,json,os,shutil,tempfile,urllib.request,zipfile
from pathlib import Path,PurePosixPath
from .config import user_dir
from .paths import application_root

FEED='https://raw.githubusercontent.com/friendzonebycarefree/ai-voice-changer/main/updates/stable.json'
RELEASES='https://github.com/friendzonebycarefree/ai-voice-changer/releases/download/'
LIMIT=16*1024*1024

def version(value):
    parts=value.split('.')
    if len(parts)!=3 or not all(p.isdigit() for p in parts):raise ValueError('Invalid update version')
    return tuple(map(int,parts))

def inspect_patch(path):
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>LIMIT:raise ValueError('Update too large')
        if len(set(z.namelist()))!=len(z.namelist()):raise ValueError('Duplicate update entries')
        manifest=json.loads(z.read('_update.json'));version(manifest['version'])
        if not manifest['files']:raise ValueError('Empty update')
        files={}
        for name,sha in manifest['files'].items():
            p=PurePosixPath(name)
            if '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe update path')
            if not (name.startswith('app/source/') or name=='app/version.json'):raise ValueError('Update cannot change models or runtime')
            data=z.read('payload/'+name)
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Update checksum mismatch')
            files[name]=data
        return manifest,files

def install_patch(path,root):
    root=Path(root).resolve();manifest,files=inspect_patch(path)
    if manifest.get('required_models'):
        actual=hashlib.sha256((root/'app/models/manifest.json').read_bytes()).hexdigest()
        if actual!=manifest['required_models']:raise ValueError('Пакет предназначен для другой версии моделей')
    # Validate all paths before writing anything, including existing symlinks.
    for name in files:
        if not (root/name).resolve().is_relative_to(root):raise ValueError('Update path escapes application')
    backup={};installed=[]
    with tempfile.TemporaryDirectory(prefix='voice-update-') as folder:
        stage=Path(folder)
        for name,data in files.items():
            p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        try:
            for name in files:
                target=root/name;backup[name]=target.read_bytes() if target.exists() else None
                target.parent.mkdir(parents=True,exist_ok=True)
                temporary=target.with_name(target.name+'.updating')
                shutil.copy2(stage/name,temporary);os.replace(temporary,target);installed.append(name)
        except Exception:
            for name in reversed(installed):
                target=root/name
                if backup[name] is None:target.unlink(missing_ok=True)
                else:target.write_bytes(backup[name])
            raise
    return manifest['version']

def apply_pending():
    pending=user_dir()/'pending-update.zip'
    if not pending.exists():return False
    try:install_patch(pending,application_root().parent)
    except Exception as error:
        (user_dir()/'update-error.txt').write_text(str(error),encoding='utf-8')
        pending.rename(user_dir()/'rejected-update.zip');return False
    pending.unlink();return True

def prepare_update(current):
    request=urllib.request.Request(FEED,headers={'User-Agent':'AI-Voice-Changer'})
    with urllib.request.urlopen(request,timeout=15) as response:meta=json.loads(response.read(65536))
    if version(meta['version'])<=version(current):return 'Установлена последняя версия'
    url=meta['url']
    if not url.startswith(RELEASES) or not url.endswith('.zip'):raise ValueError('Unexpected update source')
    pending=user_dir()/'pending-update.zip';temporary=pending.with_suffix('.download')
    try:
        with urllib.request.urlopen(url,timeout=30) as response,temporary.open('wb') as output:
            size=0
            while block:=response.read(65536):
                size+=len(block)
                if size>LIMIT:raise ValueError('Update too large')
                output.write(block)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('Update checksum mismatch')
        manifest,_=inspect_patch(temporary)
        if manifest['version']!=meta['version']:raise ValueError('Update version mismatch')
        temporary.replace(pending)
    finally:temporary.unlink(missing_ok=True)
    return 'Обновление скачано. Закройте приложение и запустите снова.'

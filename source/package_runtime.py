"""Build a self-contained Windows CPython directory with declared dependencies.

Uses wheel RECORD lists, not the developer's entire site-packages directory.
Run under the selected, tested venv. No network, no global environment changes.
"""
import argparse,importlib.metadata as metadata,json,shutil,sys,sysconfig
from pathlib import Path,PurePosixPath
from packaging.requirements import Requirement

def bundle(project,output):
    output=output/'app';output.mkdir(parents=True,exist_ok=True)
    runtime=output/'_runtime'; site=runtime/'Lib/site-packages'
    site.mkdir(parents=True,exist_ok=True)
    base=Path(sys.base_prefix)
    for name in ('python.exe','pythonw.exe','python311.dll','python3.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        if (base/name).is_file():shutil.copy2(base/name,runtime/name)
    shutil.copytree(base/'DLLs',runtime/'DLLs',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.lib','*.exp'))
    shutil.copytree(base/'Lib',runtime/'Lib',dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','ensurepip','venv','tkinter'))
    seeds=['torch','torchaudio','numpy','scipy','soundfile','soxr','psutil','PySide6-Essentials',
           'transformers','librosa','munch','einops','accelerate','safetensors']
    todo=seeds[:]; selected={}; copied=0
    while todo:
        name=todo.pop(); normalized=name.lower().replace('_','-')
        if normalized in selected:continue
        distribution=metadata.distribution(name)
        selected[normalized]=distribution.version
        for item in distribution.requires or []:
            req=Requirement(item)
            if not req.marker or req.marker.evaluate({'extra':''}):todo.append(req.name)
        for record in distribution.files or []:
            relative=PurePosixPath(str(record).replace('\\','/'))
            if '..' in relative.parts or relative.is_absolute():continue
            if '__pycache__' in relative.parts or relative.suffix in ('.pyc','.pyo','.h','.hpp','.cuh','.lib','.exp','.obj'):
                continue
            if relative.parts[:2] in [('torch','include'),('torch','test'),('torch','share')]:continue
            source=Path(distribution.locate_file(record))
            if not source.is_file():continue
            destination=site.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,destination);copied+=1
        print('copied',normalized,distribution.version,flush=True)
    from prune_payload import prune
    prune(output)
    (runtime/'python311._pth').write_text('.\nDLLs\nLib\nLib\\site-packages\n..\\source\nimport site\n',encoding='ascii')
    for folder in ('source','models','samples','LICENSES','reports'):
        shutil.copytree(project/folder,output/folder,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.obj','*.lib','*.exp','.git','*.cmd'))
    shutil.copy2(project/'README.md',output/'README.md')
    (output/'runtime-manifest.json').write_text(json.dumps({'python':sys.version,'packages':selected,'package_files':copied},indent=2),encoding='utf-8')
    print('Bundle ready:',output,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
    bundle(args.project.resolve(),args.output.resolve())

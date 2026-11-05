from pathlib import Path
import shutil
def prune(app):
 app=Path(app).resolve();root=app
 def delete(p):
  p=p.resolve();assert p.is_relative_to(root) and p!=root
  if p.is_dir():shutil.rmtree(p)
  elif p.exists():p.unlink()
 site=app/'_runtime/Lib/site-packages'
 for p in list(site.rglob('*')):
  if not p.exists():continue
  if p.is_dir() and p.name in ('tests','test','test-examples','__pycache__'):delete(p)
  elif p.is_file() and p.suffix.lower() in ('.pdb','.a','.pyx','.pxd','.h','.hpp','.lib','.obj','.exp'):delete(p)
 qt=site/'PySide6'
 for name in ('qml','include','typesystems','glue','metatypes','resources'):
  if (qt/name).exists():delete(qt/name)
 for p in list(qt.glob('*')):
  if p.suffix.lower() in ('.exe','.qmltypes') or p.name.startswith(('Qt6Quick','QtQuick','Qt6Qml','QtQml','Qt6Labs','Qt6Designer','QtDesigner','Qt6Help','QtHelp','Qt6Remote','QtRemote','Qt6Test','QtTest','Qt6Sql','QtSql','Qt6Xml','QtXml','Qt6Concurrent','QtConcurrent')):delete(p)
 for p in list((qt/'plugins').iterdir()):
  if p.name not in ('platforms','styles','imageformats','iconengines','tls','networkinformation'):delete(p)
 for p in list((qt/'translations').glob('*')):
  if not any(s in p.name for s in ('_ru.','_en.')):delete(p)
 for name in ('bin','include','share'):
  if (site/'torch'/name).exists():delete(site/'torch'/name)

"""Prepare verified models from the shipped application for a developer rebuild."""
from pathlib import Path
import shutil,sys
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'source'))
from voicechanger.assets import ModelStore
source=root.parent/'models'
if not source.is_dir():raise SystemExit('Use the complete distribution with app/models.')
store=ModelStore(source);store.verify(list(store.assets))
shutil.copytree(source,root/'models',dirs_exist_ok=True)
print('Verified model assets prepared.')

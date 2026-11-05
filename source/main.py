import argparse
import json
import os
from pathlib import Path
import sys
import warnings


def main():
    from voicechanger.updates import apply_pending
    if apply_pending():
        import runpy
        runpy.run_path(__file__,run_name='__main__')
        return 0
    from voicechanger.config import user_dir,Settings,PROFILES
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    os.environ['HF_HOME']=str(user_dir()/'hf-local')
    parser=argparse.ArgumentParser(description='Local neural AI Voice Changer')
    parser.add_argument('--convert',nargs=2,metavar=('SOURCE','OUTPUT'))
    parser.add_argument('--report',type=Path)
    parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--smoke-ui',type=Path)
    parser.add_argument('--model',choices=['seed','rvc'],default='seed')
    parser.add_argument('--device',choices=['auto','cpu','cuda'],default='auto')
    parser.add_argument('--quality',choices=['Low Latency','Balanced','High Quality'],default='Balanced')
    parser.add_argument('--profile',choices=list(PROFILES),default='Natural Female')
    args=parser.parse_args()
    warnings.filterwarnings('ignore',category=FutureWarning,module='torch')
    warnings.filterwarnings('ignore',category=__import__('torch').jit.TracerWarning)
    if args.convert:
        from voicechanger.convert import convert_file
        softness,volume=PROFILES[args.profile]
        cfg=Settings(model=args.model,backend=args.device,mode=args.quality,profile=args.profile,softness=softness,volume=volume)
        data=convert_file(*args.convert,settings=cfg)
    elif args.diagnose:
        from voicechanger.diagnostics import hardware
        from voicechanger.native import NativeAudio
        from voicechanger.paths import native_path
        data=hardware(); data['audio_devices']=NativeAudio(native_path()).devices()
    else:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from voicechanger.ui import MainWindow, STYLE
        app=QApplication(sys.argv); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
        app.setQuitOnLastWindowClosed(False)
        win=MainWindow(); win.show()
        if args.smoke_ui:
            def finish():
                win.grab().save(str(args.smoke_ui))
                win.quit_app()
            QTimer.singleShot(6000,finish)
        return app.exec()
    if args.report: args.report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    elif sys.stdout: print(json.dumps(data,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except Exception:
        import traceback
        error=traceback.format_exc()
        from voicechanger.config import user_dir
        (user_dir()/'startup-error.txt').write_text(error,encoding='utf-8')
        if sys.stderr: sys.stderr.write(error)
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,error,'AI Voice Changer — ошибка запуска',0x10)
        sys.exit(1)

import ctypes as C
from ctypes import wintypes as W
from PySide6.QtCore import QAbstractNativeEventFilter


class GlobalHotkeys(QAbstractNativeEventFilter):
    def __init__(self, callbacks):
        super().__init__()
        self.callbacks=callbacks
        self.registered=[]
        self.unavailable=[]
        for i,key in enumerate((0x78,0x79,0x7A,0x7B)):  # F9..F12
            ident=0x5A00+i
            if C.windll.user32.RegisterHotKey(None,ident,0x0001|0x0002|0x4000,key):
                self.registered.append(ident)
            else:
                self.unavailable.append(f'Ctrl+Alt+F{9+i}')

    def nativeEventFilter(self,event_type,message):
        msg=W.MSG.from_address(int(message))
        if msg.message==0x0312 and int(msg.wParam) in self.registered:
            self.callbacks[int(msg.wParam)-0x5A00]()
            return True,0
        return False,0

    def close(self):
        for ident in self.registered:
            C.windll.user32.UnregisterHotKey(None,ident)
        self.registered.clear()

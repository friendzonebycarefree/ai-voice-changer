import threading,time,unittest
from PySide6.QtCore import QCoreApplication,QEventLoop,QTimer,QThread
from voicechanger.calibration import calibrate,MAX_BLOCK_MS

class Backend:
    chunk=2880
    def __init__(self,elapsed=193):self.elapsed=elapsed;self.blocks=[]
    def warmup(self):return self.elapsed
    def configure_stream(self,ms):self.blocks.append(ms);self.chunk=ms*16

class CalibrationTests(unittest.TestCase):
    def test_193ms_uses_260ms_instead_of_rejecting_180ms(self):
        b=Backend();self.assertEqual(calibrate(b,threading.Event(),lambda _:None),260)
        self.assertEqual(b.blocks,[260])
    def test_sustained_overload_continues_with_warning(self):
        b=Backend(700)
        messages=[]
        self.assertEqual(calibrate(b,threading.Event(),messages.append),MAX_BLOCK_MS)
        self.assertTrue(any('задержкой' in text for text in messages))
        self.assertEqual(b.blocks[-1],MAX_BLOCK_MS)
    def test_cancel_stops_before_another_attempt(self):
        event=threading.Event();event.set();b=Backend()
        self.assertIsNone(calibrate(b,event,lambda _:None));self.assertEqual(b.blocks,[])
    def test_slow_warmup_keeps_qt_event_loop_responsive(self):
        app=QCoreApplication.instance() or QCoreApplication([]);loop=QEventLoop();ticks=[]
        class Slow(Backend):
            def warmup(self):time.sleep(.22);return 193
        class Worker(QThread):
            def run(self):self.result=calibrate(Slow(),threading.Event(),lambda _:None)
        worker=Worker();worker.finished.connect(loop.quit)
        timer=QTimer();timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start(20)
        worker.start();QTimer.singleShot(3000,loop.quit);loop.exec();worker.wait();timer.stop()
        self.assertEqual(worker.result,260);self.assertGreater(len(ticks),10)
        self.assertLess(max(b-a for a,b in zip(ticks,ticks[1:])),.15)

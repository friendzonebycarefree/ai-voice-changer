"""CUDA worker, separate from GUI and the C++ WASAPI event threads."""
import threading
import time
import traceback
from collections import deque
from dataclasses import replace
import numpy as np
import psutil
import soundfile as sf
import soxr
import torch
from PySide6.QtCore import QThread,Signal
from .config import user_dir
from .dsp import VoiceDSP
from .native import NativeAudio,virtual_output
from .paths import native_path

def load_backend(*args, **kwargs):
    from .neural import load_backend as load
    return load(*args, **kwargs)


class AudioWorker(QThread):
    status=Signal(str)
    metrics=Signal(dict)
    failure=Signal(str)
    active=Signal(bool)

    def __init__(self,settings,monitor=False,record=False):
        super().__init__();self.settings=settings;self.record=record
        self.stop_event=threading.Event();self.muted=threading.Event();self.monitor_enabled=threading.Event()
        if monitor:self.monitor_enabled.set()
        self._outputs=[];self._output_lock=threading.Lock();self._pending_voice=None
        self._voice_lock=threading.Lock()

    def stop(self):
        self.stop_event.set();self._mute_outputs(True)

    def request_mute(self,muted):
        if muted:self.muted.set()
        else:self.muted.clear()
        # Immediate native mute; does not wait for a GPU forward to finish.
        self._mute_outputs(muted)

    def _mute_outputs(self,value):
        with self._output_lock:
            for stream in self._outputs:
                if stream.handle:stream.mute(value)

    def update_voice(self,cfg):
        voice=replace(self.settings,profile=cfg.profile,volume=cfg.volume,softness=cfg.softness,
            noise_gate_db=cfg.noise_gate_db,auto_pitch=cfg.auto_pitch,pitch=cfg.pitch,
            target_low=cfg.target_low,target_high=cfg.target_high).validate()
        with self._voice_lock:self._pending_voice=voice

    def _add_output(self,stream):
        with self._output_lock:
            self._outputs.append(stream);stream.mute(self.muted.is_set())

    def _remove_output(self,stream):
        with self._output_lock:
            if stream in self._outputs:self._outputs.remove(stream)

    def run(self):
        from .neural import Cancelled
        streams=[];files=[];backend=None;capture=output=monitor=None
        try:
            cfg=self.settings.validate()
            if not torch.cuda.is_available() or cfg.backend=='cpu':
                raise RuntimeError('Для живого режима нужна NVIDIA/CUDA. На этом ПК доступна конверсия WAV на CPU.')
            native=NativeAudio(native_path());devices={d['id']:d for d in native.devices()}
            if cfg.microphone not in devices or devices[cfg.microphone]['flow']!='capture':raise ValueError('Выберите физический микрофон')
            if cfg.output and (cfg.output not in devices or devices[cfg.output]['flow']!='render'):
                raise ValueError('Выберите устройство вывода')
            if not cfg.output and not self.monitor_enabled.is_set():raise ValueError('Нужен виртуальный выход или прослушивание в наушниках')
            if self.monitor_enabled.is_set() and (not cfg.headphones or cfg.headphones==cfg.output):
                raise ValueError('Выберите отдельные наушники')
            self.status.emit('Загрузка моделей. Микрофон выключен.')
            backend=load_backend(cfg,progress=self.status.emit,cancel=self.stop_event)
            from .calibration import calibrate
            block_ms=calibrate(backend,self.stop_event,self.status.emit)
            if self.stop_event.is_set():return
            if cfg.output:
                output=native.open(False,cfg.output);streams.append(output);self._add_output(output)
            quality=backend.params['resampler']
            down=soxr.ResampleStream(48000,16000,1,dtype='float32',quality=quality)
            up=soxr.ResampleStream(backend.output_rate,48000,1,dtype='float32',quality=quality)
            dsp=VoiceDSP(cfg.softness,cfg.volume,cfg.noise_gate_db,backend.output_rate)
            if self.record:
                folder=user_dir()/'recordings'/time.strftime('%Y%m%d-%H%M%S')
                folder.mkdir(parents=True,exist_ok=False)
                files=[sf.SoundFile(str(folder/name),mode='w',samplerate=48000,channels=1,subtype='PCM_16')
                       for name in ('original.wav','converted.wav')]
            raw=np.zeros(backend.chunk*3,np.float32);pending=np.empty(0,np.float32)
            times=deque(maxlen=2048);processing=deque(maxlen=2048)
            last_report=time.perf_counter();last_data={};previous_drops=(0,0);slow=0
            process=psutil.Process();process.cpu_percent()
            def reset():
                nonlocal pending,dsp,previous_drops
                backend.reset();down.clear();up.clear();pending=np.empty(0,np.float32)
                dsp=VoiceDSP(cfg.softness,cfg.volume,cfg.noise_gate_db,backend.output_rate)
                for endpoint in (output,monitor):
                    if endpoint:endpoint.flush()
                if capture:
                    capture.flush();stats=capture.stats();previous_drops=(stats['dropped_samples'],stats['discontinuities'])
            while not self.stop_event.is_set():
                with self._voice_lock:
                    update,self._pending_voice=self._pending_voice,None
                if update is not None:
                    cfg=update
                    cfg.validate();backend.set_voice(cfg);dsp.set_voice(cfg)
                if self.monitor_enabled.is_set() and monitor is None:
                    if not cfg.headphones or cfg.headphones==cfg.output:raise ValueError('Для мониторинга нужны отдельные наушники')
                    monitor=native.open(False,cfg.headphones);streams.append(monitor);self._add_output(monitor)
                elif not self.monitor_enabled.is_set() and monitor:
                    self._remove_output(monitor);monitor.close();streams.remove(monitor);monitor=None
                for endpoint in (output,monitor):
                    if endpoint and endpoint.stats()['error']:raise RuntimeError('Устройство вывода отключено')
                if self.muted.is_set():
                    if capture:
                        capture.close();streams.remove(capture);capture=None;reset();self.active.emit(False)
                        self.status.emit('Выход отключён · микрофон закрыт')
                    if time.perf_counter()-last_report>.15:
                        self.metrics.emit(dict(last_data,input_peak=0.,output_peak=0.,processing_paused=True))
                        last_report=time.perf_counter()
                    self.stop_event.wait(.02);continue
                if capture is None:
                    capture=native.open(True,cfg.microphone);streams.append(capture);reset()
                    self.active.emit(True)
                    self.status.emit(f'Активно · {backend.name} · CUDA · блок {block_ms:.0f} мс'+(' · ЗАПИСЬ ВКЛ' if files else ''))
                cap=capture.stats()
                if cap['error']:raise RuntimeError('Микрофон отключён. Выход заглушён.')
                drops=(cap['dropped_samples'],cap['discontinuities'])
                if drops!=previous_drops:reset();continue
                if not capture.read(raw):self.stop_event.wait(.002);continue
                if self.muted.is_set():continue
                started=time.perf_counter()
                if files:files[0].write(raw)
                pending=np.concatenate((pending,down.resample_chunk(raw)))
                while len(pending)>=backend.chunk:
                    if self.muted.is_set() or self.stop_event.is_set():break
                    x=dsp.preprocess(pending[:backend.chunk]);pending=pending[backend.chunk:]
                    y,elapsed=backend.process(x)
                    if self.muted.is_set() or self.stop_event.is_set():break
                    rendered=up.resample_chunk(dsp.postprocess(y))
                    for endpoint in (output,monitor):
                        if endpoint:endpoint.write(rendered)
                    if files:files[1].write(rendered)
                    times.append(elapsed);processing.append((time.perf_counter()-started)*1000)
                    slow=slow+1 if elapsed>block_ms else 0
                    if slow==8:self.status.emit('Обработка отстаёт. Продолжаю с задержкой; старые фрагменты могут пропускаться.')
                if time.perf_counter()-last_report>.15 and times:
                    target=(output or monitor);out=target.stats() if target else {}
                    last_data=dict(input_peak=cap['peak'],output_peak=out.get('peak',0),
                        inference_median_ms=float(np.median(times)),inference_p95_ms=float(np.percentile(times,95)),
                        processing_median_ms=float(np.median(processing)),block_ms=block_ms,
                        capture_queue_ms=cap['queued_samples']/48,output_queue_ms=out.get('queued_samples',0)/48,
                        device_reported_ms=cap['device_latency_ms']+out.get('device_latency_ms',0),
                        resampler_pending_ms=down.delay()/16+up.delay()/48,
                        dropped_capture_samples=cap['dropped_samples'],capture_discontinuities=cap['discontinuities'],
                        output_dropped_samples=out.get('dropped_samples',0),output_silence_samples=out.get('silence_samples',0),
                        process_rss_mib=process.memory_info().rss/2**20,process_cpu_percent=process.cpu_percent(),
                        gpu_allocated_mib=torch.cuda.memory_allocated()/2**20,gpu_reserved_mib=torch.cuda.memory_reserved()/2**20,
                        stage_timings_ms=backend.last_timings.copy(),e2e_measured_ms=None,processing_paused=False)
                    self.metrics.emit(last_data);last_report=time.perf_counter()
        except Cancelled:
            pass
        except Exception as error:
            self._mute_outputs(True)
            try:(user_dir()/'last-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            except OSError:pass
            self.failure.emit(str(error))
        finally:
            self._mute_outputs(True)
            with self._output_lock:self._outputs.clear()
            for stream in reversed(streams):stream.close()
            for file in files:file.close()
            if backend is not None:backend.close()
            self.active.emit(False);self.status.emit('Остановлено · микрофон выключен')

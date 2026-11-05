from dataclasses import asdict
from pathlib import Path
import os
import time
import numpy as np
from scipy.signal import resample_poly
import soxr
import soundfile as sf
from .config import Settings
from .dsp import VoiceDSP


def convert_file(source,destination,settings=None,progress=None,cancel=None):
    from .neural import load_backend
    cfg=(settings or Settings()).validate()
    progress=progress or (lambda text:None)
    source,destination=Path(source),Path(destination)
    if source.resolve()==destination.resolve():raise ValueError('Исходный файл нельзя перезаписывать')
    info=sf.info(str(source))
    if info.frames<1 or info.duration>600:raise ValueError('Выберите непустую запись длительностью до 10 минут')
    audio,sr=sf.read(str(source),dtype='float32',always_2d=True)
    if not np.isfinite(audio).all():raise ValueError('В аудиофайле есть нечисловые отсчёты')
    x=resample_poly(audio.mean(axis=1),16000,sr).astype(np.float32)
    loaded=time.perf_counter();backend=None
    temporary=destination.with_name(destination.name+'.partial.wav')
    try:
        backend=load_backend(cfg,progress=progress,cancel=cancel)
        load_seconds=time.perf_counter()-loaded
        dsp=VoiceDSP(cfg.softness,cfg.volume,cfg.noise_gate_db,backend.output_rate)
        for start in range(0,len(x),1600):x[start:start+1600]=dsp.preprocess(x[start:start+1600])
        started=time.perf_counter();pieces=[];timings=[]
        chunk=16000*10;count=(len(x)+chunk-1)//chunk
        for index,start in enumerate(range(0,len(x),chunk)):
            backend.check_cancel();end=min(len(x),start+chunk)
            left=max(0,start-4000);right=min(len(x),end+4000)
            # Add explicit boundary context so mel/encoder rounding cannot cut
            # the final consonant. Final output retains the source duration.
            fragment=np.pad(x[left:right],(1600,1600))
            progress(f'Фрагмент {index+1}/{count}: нейросетевая конверсия · {backend.device}')
            wave=backend.infer_window(fragment)
            offset=round((start-left+1600)*backend.output_rate/16000)
            wanted=round((end-start)*backend.output_rate/16000)
            segment=wave[offset:offset+wanted]
            if len(segment)<wanted:segment=np.pad(segment,(0,wanted-len(segment)))
            pieces.append(dsp.postprocess(segment));timings.append(backend.last_timings.copy())
        generated=np.concatenate(pieces)
        output=soxr.resample(generated,backend.output_rate,48000,quality=backend.params['resampler'])
        wanted=round(len(audio)*48000/sr)
        output=np.pad(output,(0,max(0,wanted-len(output))))[:wanted]
        backend.check_cancel();progress('Сохранение обработанного WAV…')
        sf.write(str(temporary),output,48000,subtype='PCM_16',format='WAV')
        os.replace(temporary,destination)
        return {'input':str(source),'output':str(destination),'sample_rate':48000,
            'audio_seconds':len(audio)/sr,'processing_seconds':time.perf_counter()-started,
            'model_load_seconds':load_seconds,'backend':str(backend.device),'model':backend.name,
            'file_chunks':count,'stage_timings_ms':timings,'settings':asdict(cfg),
            'e2e_measured_ms':None,'subjective_quality_verified':False}
    finally:
        if backend is not None:backend.close()
        if temporary.exists():temporary.unlink()

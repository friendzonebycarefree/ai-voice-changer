"""Verified local Seed-VC and RVC adapters. No network or waveform pitch shift."""
import collections
import contextlib
import json
import sys
import time
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torch.nn.functional as F
import torchaudio
import yaml
from transformers import Wav2Vec2FeatureExtractor,Wav2Vec2Model,HubertModel
from .assets import ModelStore
from .pitch import AdaptivePitchMapper,coarse_f0
from .streaming import ContextWindow,SolaStitcher

SEED_SOURCE=Path(__file__).resolve().parent/'vendor/seed'
if str(SEED_SOURCE) not in sys.path:sys.path.insert(0,str(SEED_SOURCE))
from modules.commons import build_model,recursive_munch
from modules.audio import mel_spectrogram
from modules.campplus.DTDNN import CAMPPlus
from modules.hifigan.generator import HiFTGenerator
from modules.hifigan.f0_predictor import ConvRNNF0Predictor
from .vendor.rvc.models import SynthesizerTrnMs256NSFSid

QUALITY={
    'Low Latency':dict(block_ms=80,left_ms=480,right_ms=40,overlap_ms=20,search_ms=5,steps=4,resampler='LQ'),
    'Balanced':dict(block_ms=120,left_ms=960,right_ms=40,overlap_ms=20,search_ms=5,steps=10,resampler='MQ'),
    'High Quality':dict(block_ms=180,left_ms=1440,right_ms=60,overlap_ms=40,search_ms=10,steps=20,resampler='HQ'),
}


class Cancelled(RuntimeError):pass


class StageTimer:
    def __init__(self,device):self.device=device;self.values={};self.events=[]
    def run(self,name,fn):
        if self.device.type=='cuda':
            start,end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
            start.record();value=fn();end.record();self.events.append((name,start,end))
        else:
            start=time.perf_counter();value=fn();self.values[name]=(time.perf_counter()-start)*1000
        return value
    def finish(self):
        if self.events:
            torch.cuda.synchronize(self.device)
            self.values.update({key:start.elapsed_time(end) for key,start,end in self.events})
        return self.values


class NeuralBackend:
    sample_rate=16000
    supports_pitch_conditioning=False
    def __init__(self,cfg,store=None,progress=None,cancel=None):
        self.cfg=cfg;self.assets=store or ModelStore();self.progress=progress or (lambda text:None)
        self.cancel=cancel;self.params=QUALITY[cfg.mode].copy();self.last_timings={}
        requested=cfg.backend
        self.device=torch.device('cuda' if requested=='auto' and torch.cuda.is_available() else
                                  ('cpu' if requested=='auto' else requested))
        if self.device.type=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA недоступна; используйте файловый режим CPU')
        torch.set_num_threads(cfg.threads)

    def check_cancel(self):
        if self.cancel is not None and self.cancel.is_set():raise Cancelled('Операция отменена')

    def configure_stream(self,block_ms=None):
        if block_ms is not None:self.params['block_ms']=block_ms
        self.chunk=round(self.params['block_ms']*16)
        self.window=ContextWindow(self.chunk,round(self.params['left_ms']*16),round(self.params['right_ms']*16))
        self.stitch=SolaStitcher(round(self.chunk*self.output_rate/16000),
                                round(self.params['overlap_ms']*self.output_rate/1000),
                                round(self.params['search_ms']*self.output_rate/1000))
        self._gate=0.;self._gate_hold=0

    def reset(self):
        self.window.reset();self.stitch.reset();self._gate=0.;self._gate_hold=0
        if hasattr(self,'mapper'):self.mapper.reset()

    def set_voice(self,cfg):
        self.cfg=cfg
        if hasattr(self,'mapper'):
            self.mapper.auto=cfg.auto_pitch;self.mapper.semitones=cfg.pitch
            self.mapper.low,self.mapper.high=cfg.target_low,cfg.target_high

    @torch.inference_mode()
    def process(self,block):
        if len(block)!=self.chunk or not np.isfinite(block).all():raise ValueError('Невалидный входной блок')
        window=self.window.push(np.asarray(block,np.float32))
        self._fresh_slice=slice(self.window.left//160,(self.window.left+self.chunk)//160)
        start=time.perf_counter()
        try:wave=self.infer_window(window)
        finally:self._fresh_slice=None
        left=round(self.window.left*self.output_rate/16000)
        output=self.stitch.process(wave[left:])
        center=window[self.window.left:self.window.left+self.chunk]
        rms=float(np.sqrt(np.mean(center*center)+1e-15))
        threshold=10**(self.cfg.noise_gate_db/20)
        if rms>=threshold:self._gate_hold=round(.15*16000)
        else:self._gate_hold=max(0,self._gate_hold-self.chunk)
        desired=1. if rms>=threshold or self._gate_hold else min(1.,rms/max(threshold,1e-8))
        if rms<1e-6:desired=0.
        duration=.002 if desired>self._gate else .005
        fade=desired+(self._gate-desired)*np.exp(-np.arange(1,len(output)+1)/(duration*self.output_rate))
        output=(output*fade).astype(np.float32);self._gate=float(fade[-1])
        return output,(time.perf_counter()-start)*1000

    def warmup(self):
        results=[]
        for i in range(4):
            self.check_cancel();self.progress(f'Прогрев нейросети {i+1}/4')
            # The actual neural forward runs even for silence; gating is after
            # inference, so calibration never reports a fabricated zero cost.
            results.append(self.process(np.zeros(self.chunk,np.float32))[1])
        self.reset();return float(np.median(results[1:]))

    def close(self):
        if hasattr(self,'model') and hasattr(self.model,'cfm'):
            self.model.cfm.check_cancel=None;self.model.cfm.progress_callback=None
        for name in ('model','vocoder','encoder','camp','rmvpe','prompt','prompt_mel','style'):
            if hasattr(self,name):setattr(self,name,None)
        import gc
        gc.collect()
        if self.device.type=='cuda':torch.cuda.empty_cache()


class SeedBackend(NeuralBackend):
    output_rate=22050
    name='Seed-VC Tiny'
    def __init__(self,cfg,store=None,progress=None,cancel=None):
        super().__init__(cfg,store,progress,cancel)
        self.progress('Проверка весов Seed-VC и нейросетевого вокодера…')
        self.assets.verify(['seed.weights','seed.config','seed.camp','seed.hift','seed.hift.config',
                            'seed.encoder.weights','seed.encoder.config','seed.encoder.preprocessor','female.reference'])
        self.check_cancel()
        config=yaml.safe_load(self.assets.path('seed.config').read_text())
        args=recursive_munch(config['model_params']);args.dit_type='DiT'
        self.progress('Загрузка Seed-VC…')
        self.model=build_model(args,stage='DiT')
        state=torch.load(self.assets.path('seed.weights'),map_location='cpu',weights_only=True)['net']
        for key in self.model:
            weights={k.removeprefix('module.'):v for k,v in state[key].items()}
            if 'estimator.input_pos' in weights:
                pos=weights.pop('estimator.input_pos')
                if not torch.equal(pos,torch.arange(len(pos),dtype=pos.dtype)):raise ValueError('Неверный буфер позиций Seed-VC')
            info=self.model[key].load_state_dict(weights,strict=False)
            allowed={'estimator.input_pos','estimator.t_embedder.freqs'}
            if set(info.missing_keys)-allowed or info.unexpected_keys:raise ValueError(f'Несовместимые веса Seed-VC: {info}')
            if set(info.missing_keys)&set(dict(self.model[key].named_parameters())):raise ValueError('Не загружены обученные параметры')
            self.model[key].eval().to(self.device)
        del state
        self.model.cfm.estimator.setup_caches(max_batch_size=1,max_seq_length=8192)
        self.model.cfm.check_cancel=self.check_cancel
        self.model.cfm.progress_callback=lambda step,total:self.progress(f'Нейросеть: шаг {step}/{total}')
        self.check_cancel()
        self.camp=CAMPPlus(feat_dim=80,embedding_size=192)
        self.camp.load_state_dict(torch.load(self.assets.path('seed.camp'),map_location='cpu',weights_only=True))
        self.camp.eval().to(self.device)
        h=yaml.safe_load(self.assets.path('seed.hift.config').read_text())
        self.vocoder=HiFTGenerator(**h['hift'],f0_predictor=ConvRNNF0Predictor(**h['f0_predictor']))
        self.vocoder.load_state_dict(torch.load(self.assets.path('seed.hift'),map_location='cpu',weights_only=True))
        self.vocoder.eval().to(self.device)
        self.progress('Загрузка многоязычного Content Encoder…')
        directory=str(self.assets.path('seed.encoder.config').parent)
        self.extractor=Wav2Vec2FeatureExtractor.from_pretrained(directory,local_files_only=True)
        self.encoder=Wav2Vec2Model.from_pretrained(directory,local_files_only=True,weights_only=True,low_cpu_mem_usage=True)
        self.encoder.encoder.layers=self.encoder.encoder.layers[:args.speech_tokenizer.output_layer]
        self.encoder.eval().to(self.device)
        if self.device.type=='cuda':self.encoder.half()
        spec=config['preprocess_params']['spect_params'];self.hop=spec['hop_length']
        self.melargs=dict(n_fft=spec['n_fft'],win_size=spec['win_length'],hop_size=self.hop,
            num_mels=spec['n_mels'],sampling_rate=self.output_rate,fmin=spec.get('fmin',0),
            fmax=None if spec.get('fmax','None')=='None' else spec.get('fmax'),center=False)
        self.check_cancel();self.progress('Подготовка разрешённого женского эталона…')
        with torch.inference_mode():
            ref,sr=sf.read(str(self.assets.path('female.reference')),dtype='float32',always_2d=True)
            ref=torch.from_numpy(ref.mean(axis=1))[None].to(self.device)
            ref16=torchaudio.functional.resample(ref,sr,16000)
            refout=torchaudio.functional.resample(ref,sr,self.output_rate)
            semantic=self.semantic(ref16)
            self.prompt_mel=mel_spectrogram(refout,**self.melargs)
            bank=torchaudio.compliance.kaldi.fbank(ref16,num_mel_bins=80,dither=0,sample_frequency=16000)
            bank=bank-bank.mean(dim=0,keepdim=True);self.style=self.camp(bank[None])
            self.prompt,*_=self.model.length_regulator(semantic,
                ylens=torch.tensor([self.prompt_mel.shape[-1]],device=self.device),n_quantizers=3,f0=None)
        self.configure_stream()

    def semantic(self,wave):
        data=self.extractor([wave[0].cpu().numpy()],sampling_rate=16000,return_tensors='pt',return_attention_mask=True)
        values=data.input_values.to(self.device,dtype=next(self.encoder.parameters()).dtype)
        return self.encoder(values).last_hidden_state.float()

    @torch.inference_mode()
    def infer_window(self,audio):
        self.check_cancel();timer=StageTimer(self.device)
        audio=np.asarray(audio,np.float32)
        wave=torch.from_numpy(audio.copy())[None].to(self.device)
        content=timer.run('feature_ms',lambda:self.semantic(wave))
        resampled=torchaudio.functional.resample(wave,16000,self.output_rate)
        mel=timer.run('mel_ms',lambda:mel_spectrogram(resampled,**self.melargs))
        def neural():
            condition,*_=self.model.length_regulator(content,
                ylens=torch.tensor([mel.shape[-1]],device=self.device),n_quantizers=3,f0=None)
            combined=torch.cat((self.prompt,condition),dim=1)
            ctx=torch.autocast('cuda',dtype=torch.float16) if self.device.type=='cuda' else contextlib.nullcontext()
            with ctx:
                result=self.model.cfm.inference(combined,
                    torch.tensor([combined.shape[1]],device=self.device),self.prompt_mel,self.style,None,
                    self.params['steps'],inference_cfg_rate=.7)
            return result[:,:,self.prompt_mel.shape[-1]:]
        converted=timer.run('neural_ms',neural)
        self.check_cancel()
        generated=timer.run('vocoder_ms',lambda:self.vocoder(converted.float()))
        if isinstance(generated,tuple):generated=generated[0]
        result=generated.squeeze().float().cpu().numpy()
        self.last_timings=timer.finish();self.last_timings['f0_ms']=None
        if result.ndim!=1 or not np.isfinite(result).all():raise RuntimeError('Невалидный выход Seed-VC')
        return result.astype(np.float32)


class HubertWithProjection(HubertModel):
    def __init__(self,config):
        super().__init__(config);self.final_proj=torch.nn.Linear(config.hidden_size,config.classifier_proj_size)


class RVCBackend(NeuralBackend):
    output_rate=32000
    name='RVC v2 + RMVPE'
    supports_pitch_conditioning=True
    def __init__(self,cfg,store=None,progress=None,cancel=None):
        super().__init__(cfg,store,progress,cancel)
        self.progress('Подготовка RVC/RMVPE (первый запуск может занять время)…')
        from modules.rmvpe import RMVPE
        self.progress('Проверка весов RVC, ContentVec и RMVPE…')
        self.assets.verify(['rvc.weights','rvc.encoder.weights','rvc.encoder.config','rvc.pitch'])
        with torch.serialization.safe_globals([(collections.OrderedDict,'typing.OrderedDict')]):
            state=torch.load(self.assets.path('rvc.weights'),map_location='cpu',weights_only=True)
        args=state['params'].copy();args['spk_embed_dim']=state['weight']['emb_g.weight'].shape[0];args['emb_channels']=768
        self.model=SynthesizerTrnMs256NSFSid(**args,is_half=False);del self.model.enc_q
        info=self.model.load_state_dict(state['weight'],strict=False)
        if info.missing_keys or info.unexpected_keys:raise ValueError(f'Несовместимые веса RVC: {info}')
        self.model.dec.remove_weight_norm();self.model.flow.remove_weight_norm()
        self.model.eval().to(self.device);del state
        self.check_cancel();self.progress('Загрузка ContentVec и RMVPE…')
        directory=str(self.assets.path('rvc.encoder.config').parent)
        self.encoder=HubertWithProjection.from_pretrained(directory,local_files_only=True,weights_only=True,low_cpu_mem_usage=True).eval().to(self.device)
        self.rmvpe=RMVPE(str(self.assets.path('rvc.pitch')),is_half=False,device=self.device)
        self.mapper=AdaptivePitchMapper(cfg.auto_pitch,cfg.pitch,cfg.target_low,cfg.target_high)
        self.configure_stream()

    @torch.inference_mode()
    def infer_window(self,audio):
        self.check_cancel();timer=StageTimer(self.device)
        # HuBERT's valid convolutions lose one 20 ms feature frame at the
        # right edge. Padding supplies that frame without truncating endings.
        audio=np.pad(np.asarray(audio,np.float32),(0,320))
        wave=torch.from_numpy(audio.copy())[None].to(self.device)
        features=timer.run('feature_ms',lambda:self.encoder(wave).last_hidden_state)
        features=F.interpolate(features.transpose(1,2),scale_factor=2).transpose(1,2)
        raw_f0=timer.run('f0_ms',lambda:self.rmvpe.infer_from_audio(wave[0],thred=.03))
        f0=self.mapper.map(raw_f0,getattr(self,'_fresh_slice',None))
        n=min(len(f0),features.shape[1],len(audio)//160)
        pitch=torch.from_numpy(coarse_f0(f0[:n]))[None].to(self.device)
        frequency=torch.from_numpy(f0[:n])[None].to(self.device)
        length=torch.tensor([n],device=self.device);sid=torch.tensor([0],device=self.device)
        def neural():
            g=self.model.emb_g(sid).unsqueeze(-1)
            mean,logs,mask=self.model.enc_p(features[:,:n],pitch,length)
            prior=(mean+torch.exp(logs)*torch.randn_like(mean)*.66666)*mask
            latent=self.model.flow(prior,mask,g=g,reverse=True)
            return latent*mask,g
        latent,g=timer.run('neural_ms',neural)
        self.check_cancel()
        generated=timer.run('vocoder_ms',lambda:self.model.dec(latent,frequency,g=g))
        result=generated[0,0].float().cpu().numpy()
        self.last_timings=timer.finish()
        if result.ndim!=1 or not np.isfinite(result).all():raise RuntimeError('Невалидный выход RVC')
        return result.astype(np.float32)


def load_backend(cfg,progress=None,cancel=None):
    cls={'seed':SeedBackend,'rvc':RVCBackend}[cfg.model]
    return cls(cfg,progress=progress,cancel=cancel)

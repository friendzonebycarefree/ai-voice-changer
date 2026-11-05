"""Bounded input history and SOLA stitching, independent of the AI model."""
import numpy as np


class ContextWindow:
    def __init__(self,chunk,left,right):
        self.chunk,self.left,self.right=chunk,left,right
        self.samples=np.zeros(chunk+left+right,np.float32)

    def reset(self):self.samples.fill(0)

    def push(self,block):
        if len(block)!=self.chunk:raise ValueError('Неверная длина блока')
        self.samples[:-self.chunk]=self.samples[self.chunk:]
        self.samples[-self.chunk:]=block
        return self.samples


class SolaStitcher:
    def __init__(self,block,overlap,search):
        self.block,self.overlap,self.search=block,overlap,search
        self.tail=None
        self.fade=np.linspace(0,1,overlap,dtype=np.float32)

    def reset(self):self.tail=None

    def process(self,candidate):
        candidate=np.asarray(candidate,dtype=np.float32)
        needed=self.block+self.overlap+self.search
        if len(candidate)<needed or not np.isfinite(candidate).all():
            raise ValueError('Недостаточный или невалидный выход нейросети для SOLA')
        offset=0
        if self.tail is not None and np.sum(self.tail*self.tail)>1e-9:
            region=candidate[:self.overlap+self.search]
            numerator=np.correlate(region,self.tail,mode='valid')
            power=np.convolve(region*region,np.ones(self.overlap),mode='valid')
            scores=numerator/np.sqrt(np.maximum(power*np.sum(self.tail*self.tail),1e-12))
            offset=int(np.argmax(scores))
        output=candidate[offset:offset+self.block].copy()
        if self.tail is not None:
            output[:self.overlap]=self.tail*(1-self.fade)+output[:self.overlap]*self.fade
        self.tail=candidate[offset+self.block:offset+self.block+self.overlap].copy()
        return output

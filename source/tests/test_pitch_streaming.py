import unittest
import numpy as np
from voicechanger.pitch import AdaptivePitchMapper,coarse_f0
from voicechanger.streaming import ContextWindow,SolaStitcher


class PitchStreamingTests(unittest.TestCase):
    def test_adapts_different_male_ranges_preserving_unvoiced_and_order(self):
        result=[]
        for center in (100,170):
            mapper=AdaptivePitchMapper()
            curve=np.array([0,*np.linspace(center*.8,center*1.2,40),0])
            output=mapper.map(curve)
            self.assertEqual(output[0],0);self.assertEqual(output[-1],0)
            self.assertTrue(np.all(np.diff(output[1:-1])>0))
            result.append(np.median(output[output>0]))
        self.assertAlmostEqual(float(result[0]),float(result[1]),places=3)
        self.assertTrue(200<result[0]<260)

    def test_f0_validation_and_bounds(self):
        mapper=AdaptivePitchMapper()
        with self.assertRaises(ValueError):mapper.map(np.array([np.nan]))
        np.testing.assert_array_equal(mapper.map(np.zeros(10)),np.zeros(10))
        values=coarse_f0(np.array([0,50,200,1100,10000]))
        self.assertTrue(((values>=1)&(values<=255)).all())

    def test_context_window_does_not_grow(self):
        window=ContextWindow(80,160,40)
        for i in range(1000):self.assertEqual(len(window.push(np.ones(80,np.float32)*i)),280)
        window.reset();self.assertEqual(window.samples.sum(),0)

    def test_sola_continuity_and_exact_length(self):
        source=np.sin(np.arange(5000)*.07).astype(np.float32)
        sola=SolaStitcher(400,80,30)
        first=sola.process(source[:510])
        second=sola.process(source[400:910])
        self.assertEqual(len(first),400);self.assertEqual(len(second),400)
        self.assertLess(abs(float(second[0]-source[400])),1e-5)
        self.assertLess(np.max(abs(second-source[400:800])),1e-5)
        with self.assertRaises(ValueError):sola.process(np.zeros(10,np.float32))

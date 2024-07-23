import os
import threading
import time
import unittest
from voice.synthesis import EspeakSynthesizer
from voice.provider_contracts import WorkBudget, ProviderFailure


class SynthesisTests(unittest.TestCase):
    def test_pre_cancelled_work_never_starts_a_speech_process(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(ProviderFailure) as caught:
            EspeakSynthesizer("/must/not/run").synthesize(
                "hello", WorkBudget(stop, time.monotonic() + 1)
            )
        self.assertEqual(caught.exception.code, "cancelled")

    @unittest.skipUnless(
        os.getenv("VOICE_ESPEAK_BINARY"), "actual eSpeak binary not selected"
    )
    def test_actual_speech_has_bounded_nonempty_mono_pcm(self):
        synth = EspeakSynthesizer(os.environ["VOICE_ESPEAK_BINARY"])
        audio = synth.synthesize(
            "Please tell me the status of the Atlas service.",
            WorkBudget(threading.Event(), time.monotonic() + 3),
        )
        self.assertEqual(audio.sample_rate, 22050)
        self.assertGreater(audio.duration_ms, 1000)
        self.assertLess(audio.duration_ms, 10000)
        self.assertGreater(sum(byte != 0 for byte in audio.pcm), 1000)

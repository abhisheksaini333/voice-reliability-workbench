import math
import struct
import unittest
from voice.audio import VoiceDetector, pcm_rms
from voice.contracts import AudioFrame


def frame(index, amplitude=0):
    samples = [
        int(amplitude * math.sin(2 * math.pi * 440 * (index * 320 + sample) / 16000))
        for sample in range(320)
    ]
    return AudioFrame(index, index * 320, struct.pack("<320h", *samples))


class VoiceDetectionTests(unittest.TestCase):
    def test_hysteresis_keeps_preroll_and_finishes_after_silence(self):
        detector = VoiceDetector()
        events = []
        for index in range(40):
            events.extend(detector.feed(frame(index, 9000 if 5 <= index < 15 else 0)))
        self.assertEqual(
            [event.kind for event in events], ["speech_start", "utterance"]
        )
        self.assertEqual(events[0].detected_sample, 7 * 320)
        self.assertEqual(events[1].start_sample, 0)
        self.assertEqual(len(events[1].pcm), 35 * 640)
        self.assertFalse(events[1].truncated)
        self.assertFalse(detector.active)
        self.assertLessEqual(detector.buffered_frames, 10)

    def test_short_noise_is_not_an_utterance_and_long_speech_is_bounded(self):
        detector = VoiceDetector(max_frames=30)
        self.assertEqual(detector.feed(frame(0, 9000)), [])
        self.assertEqual(detector.feed(frame(1, 0)), [])
        events = []
        for index in range(2, 80):
            events.extend(detector.feed(frame(index, 9000)))
            self.assertLessEqual(detector.buffered_frames, 30)
        completed = [event for event in events if event.kind == "utterance"]
        self.assertTrue(completed)
        self.assertTrue(all(event.truncated for event in completed))
        self.assertTrue(all(len(event.pcm) <= 30 * 640 for event in completed))

    def test_pcm_rms_and_explicit_flush(self):
        self.assertEqual(pcm_rms(frame(0).pcm), 0)
        self.assertGreater(pcm_rms(frame(0, 9000).pcm), 0.1)
        detector = VoiceDetector()
        for index in range(4):
            detector.feed(frame(index, 9000))
        self.assertEqual(len(detector.flush().pcm), 4 * 640)
        self.assertIsNone(detector.flush())

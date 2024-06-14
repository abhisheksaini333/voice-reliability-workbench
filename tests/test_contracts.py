import struct
import unittest
from voice.contracts import AudioFrame, AudioSequence, ProtocolError, parse_control


class AudioContractTests(unittest.TestCase):
    def test_pcm_frame_roundtrip_and_sample_clock(self):
        frame = AudioFrame(2, 640, b"\x00\x00" * 320)
        parsed = AudioFrame.decode(frame.encode())
        self.assertEqual(parsed, frame)
        self.assertEqual(parsed.capture_ms, 40)

    def test_malformed_frame_and_clock_are_rejected_without_advancing_sequence(self):
        sequence = AudioSequence()
        for raw in (b"", b"\x00" * 647, b"\x00" * 649):
            with self.assertRaises(ProtocolError):
                AudioFrame.decode(raw)
        good = AudioFrame(0, 0, b"\x00\x00" * 320)
        sequence.accept(good)
        for frame in (good, AudioFrame(2, 640, good.pcm), AudioFrame(1, 0, good.pcm)):
            with self.assertRaises(ProtocolError):
                sequence.accept(frame)
        sequence.accept(AudioFrame(1, 320, good.pcm))
        self.assertEqual(sequence.frames, 2)

    def test_controls_reject_unknown_fields_and_boolean_audio_identifiers(self):
        self.assertEqual(parse_control('{"type":"start"}'), {"type": "start"})
        self.assertEqual(
            parse_control('{"type":"ack","epoch":3,"sequence":2}')["epoch"], 3
        )
        for raw in (
            "[]",
            '{"type":[]}',
            '{"type":"tool","service":{}}',
            "[" * 1500 + "]" * 1500,
            '{"type":"start","tenant":"other"}',
            '{"type":"ack","epoch":true,"sequence":0}',
            '{"type":"run_shell"}',
            '{"type":"ack","epoch":1}',
            "x" * 4097,
        ):
            with self.assertRaises(ProtocolError):
                parse_control(raw)

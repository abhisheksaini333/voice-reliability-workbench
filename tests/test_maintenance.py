import unittest, tempfile, pathlib, json, math, os
from unittest.mock import patch, Mock

class Maintenance(unittest.TestCase):

    def test_vrw01(self):
        from voice.contracts import parse_control, ProtocolError
        for raw in ('{"type":"start","type":"stop"}', '{"type":"ack","epoch":1,"epoch":2,"sequence":0}', '{"type":"tool","service":"atlas","service":"beacon"}'):
            with self.assertRaises(ProtocolError): parse_control(raw)
        self.assertEqual(parse_control('{"type":"start"}'), {'type':'start'})

    def test_vrw02(self):
        from voice.audio import VoiceDetector
        for key in ('attack_frames','silence_frames','preroll_frames','max_frames'):
            for value in (True, 1.5, '3', 1501):
                with self.assertRaises(ValueError): VoiceDetector(**{key:value})
        for threshold in (True, '0.02', float('nan'), float('inf')):
            with self.assertRaises(ValueError): VoiceDetector(threshold=threshold)
        self.assertEqual(VoiceDetector().max_frames,600)

    def test_vrw03(self):
        from voice.provider_contracts import SpeechAudio, ProviderFailure
        for pcm,rate in (('aa',22050),([0,0],22050),(b'aa',22050.0),(b'aa',True)):
            with self.assertRaisesRegex(ProviderFailure,'invalid_speech_audio'): SpeechAudio(pcm,rate)
        self.assertGreater(SpeechAudio(b'aa',22050).duration_ms,0)

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

    def test_vrw04(self):
        import asyncio
        from voice.worker import NativeWorker
        from voice.provider_contracts import ProviderFailure
        async def scenario():
            worker=NativeWorker(); operation=Mock(return_value='done')
            for timeout in (True,'2',None,float('nan'),float('inf'),0):
                with self.assertRaisesRegex(ProviderFailure,'invalid_job'):
                    await worker.run('job','stt',operation,timeout)
                self.assertIsNone(worker.active)
            operation.assert_not_called()
            self.assertEqual(await worker.run('valid','stt',operation,1),'done')
        asyncio.run(scenario())

    def test_vrw05(self):
        import asyncio
        from voice.playback import PlaybackWindow, StaleAudio
        async def scenario():
            window=PlaybackWindow()
            await window.reset(0)
            self.assertEqual(await window.reserve(0),0)
            await window.reset(0)
            self.assertEqual(window.pending,[0])
            self.assertEqual(await window.reserve(0),1)
            self.assertFalse(await window.acknowledge(False,0))
            self.assertFalse(await window.acknowledge(0,False))
            with self.assertRaises(StaleAudio): await window.reserve(False)
            with self.assertRaises(StaleAudio): await window.reset(True)
            await window.reset(1)
            self.assertEqual(window.pending,[])
            self.assertEqual(await window.reserve(1),0)
            with self.assertRaises(StaleAudio): await window.reset(0)
        asyncio.run(scenario())

    def test_vrw06(self):
        from voice.tools import ToolManager, ToolError
        from voice.state import TurnIdentity
        identity=TurnIdentity('session',1,1)
        for timeout,now in ((True,1),('2',1),(float('nan'),1),(1,float('nan')),(1,float('inf'))):
            manager=ToolManager(lambda identity:True,clock=lambda:now)
            with self.assertRaises(ToolError): manager.issue(identity,'atlas',timeout)
            self.assertEqual(manager.receipts,{})
        manager=ToolManager(lambda identity:True,clock=lambda:10)
        self.assertEqual(manager.issue(identity,'atlas',2).deadline,12)

    def test_vrw07(self):
        import asyncio
        from voice.tools import ToolManager
        from voice.state import TurnIdentity
        async def scenario():
            now=[10]; current=[True]; identity=TurnIdentity('session',1,1)
            manager=ToolManager(lambda identity:current[0],clock=lambda:now[0])
            stale=manager.issue(identity,'atlas'); current[0]=False
            operation=Mock(return_value=None)
            self.assertEqual((await manager.execute(stale,operation))['state'],'cancelled')
            operation.assert_not_called()
            current[0]=True; expired=manager.issue(identity,'atlas'); now[0]=20
            self.assertEqual((await manager.execute(expired,operation))['state'],'timed_out')
            operation.assert_not_called()
        asyncio.run(scenario())

    def test_vrw08(self):
        from voice.state import SessionState, StateError
        valid=dict(id='session',connection=1,epoch=3,phase='operator')
        for key,value in (('id',''),('id',7),('id','bad\nname'),('connection',True),('connection',-1),('epoch',1.5),('phase','unknown'),('phase',[])):
            with self.assertRaises(StateError): SessionState.restore({**valid,key:value})
        for value in (None,{},[]):
            with self.assertRaises(StateError): SessionState.restore(value)
        restored=SessionState.restore(valid)
        self.assertFalse(restored.connected); self.assertFalse(restored.recording)
        self.assertEqual(restored.phase,'operator')

    def test_vrw09(self):
        from voice.evaluation import words, word_error_rate
        for value in (None,17,[], 'a'*20001):
            with self.assertRaises(ValueError): words(value)
        self.assertEqual(words("It's a test"),["it's",'a','test'])
        self.assertEqual(word_error_rate('a b','a c')['substitutions'],1)

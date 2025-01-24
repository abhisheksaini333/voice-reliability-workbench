import unittest, tempfile, pathlib, json, math, os
from unittest.mock import patch, Mock

class Maintenance(unittest.TestCase):

    def test_vrw01(self):
        from voice.contracts import parse_control, ProtocolError
        for raw in ('{"type":"start","type":"stop"}', '{"type":"ack","epoch":1,"epoch":2,"sequence":0}', '{"type":"tool","service":"atlas","service":"beacon"}'):
            with self.assertRaises(ProtocolError): parse_control(raw)
        self.assertEqual(parse_control('{"type":"start"}'), {'type':'start'})

import copy
import sys
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from d0_plan_envelope import seal, unseal


class EnvelopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=3072)

    def test_full_plan_is_not_plaintext_and_roundtrips_exactly(self):
        raw=b'{"internal_endpoint":"synthetic.example.invalid","changes":[]}'
        e=seal(raw,{'workflowSha':'a'*40,'planSha256':'b'*64},self.key.public_key())
        self.assertNotIn('synthetic.example.invalid',str(e))
        self.assertEqual(raw,unseal(e,self.key))

    def test_tampered_context_ciphertext_or_wrong_key_is_rejected(self):
        original=seal(b'private-test-plan',{'runId':'123'},self.key.public_key())
        for key,value in [('context',{'runId':'456'}),('ciphertext','AAAA'),('plainSha256','0'*64)]:
            e=copy.deepcopy(original);e[key]=value
            with self.assertRaises(Exception):unseal(e,self.key)
        other=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        with self.assertRaises(Exception):unseal(original,other)

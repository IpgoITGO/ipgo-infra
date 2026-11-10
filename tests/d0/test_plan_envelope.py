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

    def test_refresh_cli_seals_with_same_guard_mode_and_digest(self):
        import contextlib,io,json,os,tempfile
        from unittest.mock import patch
        from cryptography.hazmat.primitives import serialization
        from d0_plan_envelope import main
        from d0_plan_guard import review
        from test_task_refresh import plan,IMAGE
        p=plan();expected=review(p,refresh=True,image_uri=IMAGE+'b'*64)['planSha256']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'plan.json').write_text(json.dumps(p))
            (root/'d0-iam-snapshot.json').write_text('{"iamSnapshotSha256":"reviewed"}')
            pub=root/'pub.pem';pub.write_bytes(self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
            env={'RUNNER_TEMP':tmp,'D0_TERRAFORM_JSON':json.dumps({'configuration':{'image_uri':IMAGE+'b'*64}}),
                 'REFRESH_TASKS':'true','PROTECT_TASKS':'false','REVOKE_RUNTIME':'false','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'1'}
            with patch.dict(os.environ,env),patch.object(sys,'argv',['seal','seal',str(root/'plan.json'),str(root/'out.json')]),patch('d0_plan_envelope.PUBLIC_KEY',pub),patch('d0_iam_preflight.validate_snapshot'),contextlib.redirect_stdout(io.StringIO()):main()
            envelope=json.loads((root/'out.json').read_text())
            self.assertEqual(expected,envelope['context']['planSha256'])
            self.assertEqual(p,json.loads(unseal(envelope,self.key)))

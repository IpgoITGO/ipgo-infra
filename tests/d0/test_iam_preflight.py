import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from d0_iam_preflight import collect, digest, fingerprint, validate_snapshot, check_plan, persist, main, PreflightError
from d0_plan_envelope import unseal

ACCOUNT = '123456789012'
PREFIX = f'arn:aws:iam::{ACCOUNT}:role/'
CALLER = PREFIX + 'ipgo-github-terraform-apply'
CFG = {'enabled': True, 'runtime_enabled': False, 'configuration': {
    'account_id': ACCOUNT, 'bootstrap_execution_role_arn': PREFIX + 'ipgo-dev-database-bootstrap-execution'}}
POLICY = {'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':'example:Read','Resource':'*'}]}
MANAGED = 'arn:aws:iam::aws:policy/PowerUserAccess'
BOUNDARY = f'arn:aws:iam::{ACCOUNT}:policy/test-boundary'


class FakeSts:
    def __init__(self, session='one', account=ACCOUNT):
        self.session, self.account = session, account

    def get_caller_identity(self):
        return {'Account':self.account,'Arn':f'arn:aws:sts::{self.account}:assumed-role/ipgo-github-terraform-apply/{self.session}', 'UserId':'example:'+self.session}


class FakeIam:
    def __init__(self, fail=None, missing=None, page_fault=None, new_exists=False, encoded=False, version_drift=False):
        self.fail,self.missing,self.page_fault=fail,missing,page_fault
        self.new_exists,self.encoded,self.version_drift=new_exists,encoded,version_drift
        self.calls=[]

    def record(self, api, **kwargs):
        self.calls.append((api,kwargs))
        if self.fail == api:
            raise ClientError({'Error':{'Code':'AccessDenied','Message':'never-log-this-private-message'}},api)

    def get_role(self, RoleName):
        self.record('GetRole', RoleName=RoleName)
        if self.missing==RoleName or ('-d0-' in RoleName and not self.new_exists):
            raise ClientError({'Error':{'Code':'NoSuchEntity','Message':'missing'}},'GetRole')
        result={'Arn':PREFIX+RoleName,'RoleName':RoleName,'RoleId':'AROAEXAMPLE'+RoleName,
                'MaxSessionDuration':3600,'AssumeRolePolicyDocument':copy.deepcopy(POLICY)}
        if 'bootstrap' in RoleName:
            result['PermissionsBoundary']={'PermissionsBoundaryType':'Policy','PermissionsBoundaryArn':BOUNDARY}
        return {'Role':result}

    def list_role_policies(self, RoleName, Marker=None):
        self.record('ListRolePolicies', RoleName=RoleName, Marker=Marker)
        if self.page_fault == 'missing-marker':
            return {'PolicyNames':['first'],'IsTruncated':True}
        if Marker is None:
            return {'PolicyNames':['first'],'IsTruncated':True,'Marker':'next'}
        return {'PolicyNames':['second'],'IsTruncated':self.page_fault=='repeated-marker','Marker':'next'}

    def get_role_policy(self, RoleName, PolicyName):
        self.record('GetRolePolicy', RoleName=RoleName, PolicyName=PolicyName)
        return {'RoleName':RoleName,'PolicyName':PolicyName,
                'PolicyDocument':quote(json.dumps(POLICY)) if self.encoded else copy.deepcopy(POLICY)}

    def list_attached_role_policies(self, RoleName, Marker=None):
        self.record('ListAttachedRolePolicies', RoleName=RoleName, Marker=Marker)
        if Marker is None:
            return {'AttachedPolicies':[{'PolicyArn':MANAGED,'PolicyName':'PowerUserAccess'}], 'IsTruncated':True,'Marker':'attached-next'}
        return {'AttachedPolicies':[{'PolicyArn':BOUNDARY,'PolicyName':'test-boundary'}], 'IsTruncated':False}

    def get_policy(self, PolicyArn):
        self.record('GetPolicy', PolicyArn=PolicyArn)
        return {'Policy':{'Arn':PolicyArn,'DefaultVersionId':'v2'}}

    def get_policy_version(self, PolicyArn, VersionId):
        self.record('GetPolicyVersion', PolicyArn=PolicyArn, VersionId=VersionId)
        return {'PolicyVersion':{'VersionId':VersionId,'IsDefaultVersion':not self.version_drift,'Document':copy.deepcopy(POLICY)}}


def snapshot(iam=None, sts=None, operation='plan', install=False):
    return collect(sts or FakeSts(), iam or FakeIam(), CFG['configuration'], CALLER, 'a'*40,
                   digest(CFG), run_id='123',operation=operation,install=install)


def environment(operation='plan'):
    return {'AWS_ACCOUNT_ID':ACCOUNT,'GITHUB_SHA':'a'*40,'EXPECTED_SHA':'a'*40,'GITHUB_RUN_ID':'123',
            'AWS_APPLY_ROLE_ARN':CALLER,'OPERATION':operation,'GITHUB_REPOSITORY':'IpgoITGO/ipgo-infra',
            'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/dev','GITHUB_RUN_ATTEMPT':'1',
            'D0_INFRA_ENABLED':'true','D0_TERRAFORM_JSON':json.dumps(CFG)}


class IamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=3072)

    def test_reads_all_pages_default_versions_boundary_and_expected_new_absence(self):
        iam=FakeIam(encoded=True);s=snapshot(iam)
        self.assertTrue(s['success'])
        self.assertEqual({'first','second'},set(s['roles']['caller']['inline']))
        self.assertFalse(s['roles']['execution']['exists'])
        self.assertFalse(s['roles']['installer']['exists'])
        self.assertEqual(BOUNDARY,s['roles']['bootstrap']['permissionsBoundary'])
        self.assertEqual(2,len([c for c in iam.calls if c[0]=='GetPolicyVersion']))
        self.assertTrue(all(c[1]['VersionId']=='v2' for c in iam.calls if c[0]=='GetPolicyVersion'))
        self.assertTrue(all(c[0].startswith(('Get','List')) for c in iam.calls))
        self.assertEqual(POLICY,s['roles']['caller']['inline']['first'])

    def test_semantic_fingerprint_ignores_session_run_time_but_binds_policy_source_and_config(self):
        a=snapshot();b=snapshot(sts=FakeSts('different'))
        self.assertEqual(a['iamSnapshotSha256'],b['iamSnapshotSha256'])
        b['runId']='another';b['observedAt']='later'
        self.assertEqual(a['iamSnapshotSha256'],fingerprint(b))
        for field,value in [('sourceSha','b'*40),('configurationSha256','c'*64)]:
            b=copy.deepcopy(a);b[field]=value;self.assertNotEqual(a['iamSnapshotSha256'],fingerprint(b))
        b=copy.deepcopy(a);b['managedPolicies'][MANAGED]['versionId']='v3'
        self.assertNotEqual(a['iamSnapshotSha256'],fingerprint(b))

    def test_access_denied_stops_at_first_api_and_does_not_expose_sdk_message(self):
        for api in ['GetRole','ListRolePolicies','GetRolePolicy','ListAttachedRolePolicies','GetPolicy','GetPolicyVersion']:
            iam=FakeIam(fail=api);out=io.StringIO()
            with contextlib.redirect_stdout(out):s=snapshot(iam)
            self.assertFalse(s['success']);self.assertEqual('AccessDenied',s['failure']['code'])
            self.assertEqual(api,iam.calls[-1][0]);self.assertNotIn('never-log',json.dumps(s))
            self.assertEqual('',out.getvalue())

    def test_missing_required_role_and_install_role_are_not_treated_as_new_absence(self):
        s=snapshot(FakeIam(missing='ipgo-dev-database-bootstrap-execution'))
        self.assertFalse(s['success']);self.assertEqual('bootstrap',s['failure']['target'])
        s=snapshot(install=True);self.assertFalse(s['success']);self.assertEqual('execution',s['failure']['target'])

    def test_incomplete_pages_and_changed_default_version_fail_closed(self):
        for kwargs in [{'page_fault':'missing-marker'},{'page_fault':'repeated-marker'},{'version_drift':True}]:
            with self.subTest(kwargs=kwargs):self.assertFalse(snapshot(FakeIam(**kwargs))['success'])

    def test_cross_account_policy_reference_is_rejected_without_fetching_it(self):
        iam=FakeIam();original=iam.get_role
        def role(**kwargs):
            r=original(**kwargs)
            r['Role']['PermissionsBoundary']={'PermissionsBoundaryType':'Policy','PermissionsBoundaryArn':'arn:aws:iam::999999999999:policy/other'}
            return r
        iam.get_role=role
        s=snapshot(iam);self.assertFalse(s['success']);self.assertEqual('POLICY_ARN',s['failure']['code'])
        self.assertFalse(any('999999999999' in str(c) for c in iam.calls))

    def test_wrong_actual_account_is_rejected_before_iam_calls(self):
        iam=FakeIam();s=snapshot(iam,FakeSts(account='999999999999'))
        self.assertFalse(s['success']);self.assertEqual([],iam.calls)

    def test_reviewed_snapshot_context_and_apply_fingerprint_are_required(self):
        s=snapshot();validate_snapshot(s,environment(),CFG)
        for field,value in [('GITHUB_SHA','b'*40),('GITHUB_RUN_ID','999'),('AWS_ACCOUNT_ID','999999999999')]:
            env=environment();env[field]=value
            with self.subTest(field=field),self.assertRaises(PreflightError):validate_snapshot(s,env,CFG)
        s=snapshot(operation='apply');env=environment('apply')
        with self.assertRaisesRegex(PreflightError,'IAM_SNAPSHOT_CHANGED'):validate_snapshot(s,env,CFG)
        env['EXPECTED_IAM_SNAPSHOT_SHA256']=s['iamSnapshotSha256'];validate_snapshot(s,env,CFG)
        s['roles']['caller']['inline'].clear()
        with self.assertRaisesRegex(PreflightError,'INTEGRITY'):validate_snapshot(s,env,CFG)

    def test_recovery_requires_install_roles_and_reviewed_iam_fingerprint(self):
        s=snapshot(FakeIam(new_exists=True),operation='deactivate',install=True)
        env=environment('deactivate')
        with self.assertRaisesRegex(PreflightError,'IAM_SNAPSHOT_CHANGED'):validate_snapshot(s,env,CFG)
        env['EXPECTED_IAM_SNAPSHOT_SHA256']=s['iamSnapshotSha256'];validate_snapshot(s,env,CFG)
        missing=snapshot(operation='deactivate',install=True)
        self.assertFalse(missing['success'])

    def test_existing_new_role_collides_with_create_plan(self):
        p={'resource_changes':[{'type':'aws_iam_role','change':{'actions':['create'],'after':{'name':'ipgo-dev-d0-execution'}}}]}
        check_plan(snapshot(),p)
        with self.assertRaisesRegex(PreflightError,'COLLISION'):check_plan(snapshot(FakeIam(new_exists=True)),p)

    def test_failed_snapshot_is_encrypted_roundtrips_and_plain_file_is_0600(self):
        s=snapshot(FakeIam(fail='GetRole'))
        with tempfile.TemporaryDirectory() as d:
            persist(s,d,self.key.public_key())
            envelope=json.loads(Path(d,'d0-iam-snapshot-envelope.json').read_text())
            self.assertNotIn(CALLER,json.dumps(envelope))
            self.assertEqual(s,json.loads(unseal(envelope,self.key)))
            self.assertEqual(0o600,Path(d,'d0-iam-snapshot.json').stat().st_mode & 0o777)

    def test_seal_failure_does_not_produce_successful_evidence(self):
        with tempfile.TemporaryDirectory() as d,patch('d0_plan_envelope.seal',side_effect=RuntimeError('seal failure')):
            with self.assertRaises(RuntimeError):persist(snapshot(),d,self.key.public_key())
            self.assertFalse(Path(d,'d0-iam-snapshot-envelope.json').exists())

    def test_cli_failure_preserves_only_encrypted_upload_and_never_logs_policy_or_arn(self):
        with tempfile.TemporaryDirectory() as d:
            pub=Path(d,'test-public.pem');pub.write_bytes(self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
            env=environment();env['RUNNER_TEMP']=d;out=io.StringIO()
            with patch.dict(os.environ,env),patch('boto3.client',side_effect=[FakeSts(),FakeIam(fail='GetRole')]),patch('d0_plan_envelope.PUBLIC_KEY',pub),contextlib.redirect_stdout(out):
                with self.assertRaisesRegex(PreflightError,'IAM_PREFLIGHT_FAILED'):main()
            self.assertIn('AccessDenied',out.getvalue());self.assertNotIn('arn:',out.getvalue())
            self.assertFalse(json.loads(unseal(json.loads(Path(d,'d0-iam-snapshot-envelope.json').read_text()),self.key))['success'])

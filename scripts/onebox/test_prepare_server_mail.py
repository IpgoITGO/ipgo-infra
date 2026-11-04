import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('mail_candidate', Path(__file__).with_name('prepare-server-mail.py'))
mail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mail)

ACCOUNT = '123456789012'
DEFINITION = f'arn:aws:ecs:ap-northeast-2:{ACCOUNT}:task-definition/ipgo-dev-onebox-server:5'
SECRET = f'arn:aws:secretsmanager:ap-northeast-2:{ACCOUNT}:secret:/ipgo/dev/server-mail-password-Abc123'
IMAGE = f'{ACCOUNT}.dkr.ecr.ap-northeast-2.amazonaws.com/ipgo/server:pinned'
MAIL_CONFIG = {'SPRING_MAIL_USERNAME': 'synthetic@example.invalid', 'IPGO_MAIL_FROM': 'synthetic@example.invalid'}


class MailCandidateTests(unittest.TestCase):
    def setUp(self):
        self.original = {'taskDefinition': {
            'taskDefinitionArn': DEFINITION, 'family': 'ipgo-dev-onebox-server', 'revision': 5,
            'status': 'ACTIVE', 'networkMode': 'bridge', 'requiresCompatibilities': ['EC2'],
            'executionRoleArn': f'arn:aws:iam::{ACCOUNT}:role/execution',
            'taskRoleArn': f'arn:aws:iam::{ACCOUNT}:role/server',
            'containerDefinitions': [{'name': 'server', 'image': IMAGE, 'memory': 448,
                'environment': [{'name': 'SPRING_FLYWAY_ENABLED', 'value': 'false'}],
                'secrets': [{'name': 'IPGO_JWT_SECRET', 'valueFrom': 'existing-reference'}],
                'healthCheck': {'command': ['CMD-SHELL', 'health']}}],
        }}

    def prepare(self, **changes):
        return mail.prepare(self.original, **({'expected_definition': DEFINITION,
            'expected_image': IMAGE, 'secret_arn': SECRET, 'mail_config': MAIL_CONFIG} | changes))

    def test_only_mail_configuration_changes_and_input_is_immutable(self):
        before = copy.deepcopy(self.original)
        candidate, policy = self.prepare()
        self.assertEqual(self.original, before)
        self.assertNotIn('taskDefinitionArn', candidate)
        server = candidate['containerDefinitions'][0]
        old_server = before['taskDefinition']['containerDefinitions'][0]
        for key in ['image', 'memory', 'healthCheck']:
            self.assertEqual(server[key], old_server[key])
        for key in ['taskRoleArn', 'executionRoleArn', 'networkMode']:
            self.assertEqual(candidate[key], before['taskDefinition'][key])
        self.assertIn(old_server['environment'][0], server['environment'])
        self.assertIn(old_server['secrets'][0], server['secrets'])
        self.assertEqual(len(server['secrets']), 2)
        password = next(x for x in server['secrets'] if x['name'] == 'SPRING_MAIL_PASSWORD')
        self.assertEqual(password['valueFrom'], SECRET)
        self.assertEqual(policy['Statement'][0]['Resource'], [SECRET])
        self.assertEqual(policy['Statement'][0]['Action'], ['secretsmanager:GetSecretValue'])
        env = {x['name']: x['value'] for x in server['environment']}
        self.assertEqual(env['SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_REQUIRED'], 'true')
        self.assertFalse(set(env) & set(mail.MAIL_SECRETS))

    def test_stale_definition_or_wrong_image_is_blocked(self):
        for changes in [{'expected_definition': DEFINITION[:-1] + '6'}, {'expected_image': 'other'}]:
            with self.assertRaises(ValueError): self.prepare(**changes)

    def test_cross_account_region_or_secret_json_key_is_blocked(self):
        for secret in [SECRET.replace(ACCOUNT, '999999999999'), SECRET.replace('ap-northeast-2', 'us-east-1'), SECRET + ':password::', SECRET.replace('server-mail-password', 'another-secret')]:
            with self.assertRaises(ValueError): self.prepare(secret_arn=secret)

    def test_external_environment_file_or_unknown_fields_are_blocked(self):
        self.original['taskDefinition']['containerDefinitions'][0]['environmentFiles'] = [{'value': 'external'}]
        with self.assertRaises(ValueError): self.prepare()
        self.original['taskDefinition']['containerDefinitions'][0].pop('environmentFiles')
        self.original['taskDefinition']['newUnsupportedField'] = True
        with self.assertRaises(ValueError): self.prepare()

    def test_replacing_old_mail_settings_does_not_duplicate_or_expose_credentials(self):
        c = self.original['taskDefinition']['containerDefinitions'][0]
        c['environment'].append({'name': 'SPRING_MAIL_PASSWORD', 'value': 'synthetic-placeholder'})
        c['secrets'].append({'name': 'SPRING_MAIL_USERNAME', 'valueFrom': 'old-reference'})
        candidate, _ = self.prepare()
        c = candidate['containerDefinitions'][0]
        self.assertNotIn('SPRING_MAIL_PASSWORD', [e['name'] for e in c['environment']])
        self.assertEqual([s['name'] for s in c['secrets']].count('SPRING_MAIL_USERNAME'), 0)

    def test_unreviewed_mail_debug_options_are_blocked(self):
        self.original['taskDefinition']['containerDefinitions'][0]['environment'].append(
            {'name': 'SPRING_MAIL_PROPERTIES_MAIL_DEBUG', 'value': 'true'})
        with self.assertRaises(ValueError): self.prepare()

    def test_mail_config_rejects_password_fields_and_different_or_invalid_addresses(self):
        for config in [MAIL_CONFIG | {'SPRING_MAIL_PASSWORD': 'synthetic-placeholder'},
                       MAIL_CONFIG | {'IPGO_MAIL_FROM': 'other@example.invalid'},
                       MAIL_CONFIG | {'SPRING_MAIL_USERNAME': 'bad\naddress'}]:
            with self.assertRaises(ValueError): self.prepare(mail_config=config)

    def test_cli_creates_private_artifacts_and_preserves_tags(self):
        self.original['tags'] = [{'key': 'owner', 'value': 'synthetic'}]
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'input.json'
            source.write_text(json.dumps(self.original))
            source.chmod(0o600)
            config = Path(root) / 'mail-config.json'
            config.write_text(json.dumps(MAIL_CONFIG))
            config.chmod(0o600)
            output = Path(root) / 'candidate'
            process = subprocess.run([sys.executable, str(Path(__file__).with_name('prepare-server-mail.py')),
                '--input', str(source), '--expected-definition', DEFINITION, '--expected-image', IMAGE,
                '--secret-arn', SECRET, '--mail-config', str(config), '--output-dir', str(output)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for path in output.iterdir(): self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            task = json.loads((output / 'task-definition.json').read_text())
            self.assertEqual(task['tags'], self.original['tags'])
            self.assertFalse(json.loads((output / 'manifest.json').read_text())['deployment_authorized'])
            self.assertNotIn(SECRET, process.stdout)


if __name__ == '__main__': unittest.main()

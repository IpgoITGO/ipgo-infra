"""배포 계약을 나타낸 합성 TD. 실제 AWS·외부 LLM 호출은 하지 않는다."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/rds_offhours'))
from aws_api import AWS, LLM_DISABLE_CONTRACT, llm_credentials_absent
from policy import digest


class LLMContractTests(unittest.TestCase):
    def setUp(self):
        self.definitions = {
            'server:5': [{'name': 'server', 'image': 'server:fixed-source',
                          'environment': [{'name': 'IPGO_ENGINE_ENABLED', 'value': 'true'}],
                          'secrets': [{'name': 'DB_PASSWORD', 'valueFrom': 'db-secret'},
                                      {'name': 'JWT_SECRET', 'valueFrom': 'jwt-secret'}]}],
            'ai:4': [{'name': 'ai-api', 'image': 'ai:fixed-source', 'environment': [
                {'name': 'ENGINE_MODE', 'value': 'real'},
                {'name': 'IPGO_EMBEDDED_WORKER_ENABLED', 'value': 'true'}]}],
        }
        self.ecs = Mock()
        self.ecs.describe_services.side_effect = lambda **kw: {
            'services': [{'taskDefinition': {'server': 'server:5', 'ai': 'ai:4'}[kw['services'][0]]}]}
        self.ecs.describe_task_definition.side_effect = lambda **kw: {
            'taskDefinition': {'containerDefinitions': self.definitions[kw['taskDefinition']]}}
        self.api = AWS({'cluster_arn': 'cluster', 'service_arns': ['arn:service/server', 'arn:service/ai'],
                        'service_task_arns': ['server:5', 'ai:4']}, lambda name: self.ecs)

    def manifest(self):
        return {'llm_disable_contract': LLM_DISABLE_CONTRACT,
                'service_definitions': {name: digest(self.definitions[td])
                                        for name, td in [('server', 'server:5'), ('ai', 'ai:4')]}}

    def test_real_calculation_without_enable_flags_satisfies_reviewed_key_absence(self):
        self.assertEqual(self.api.sources_match(self.manifest()), (True, True))
        self.ecs.start_task.assert_not_called()
        self.ecs.update_service.assert_not_called()

    def test_contract_must_be_reviewed_even_when_explicit_flag_is_false(self):
        self.definitions['ai:4'][0]['environment'].append({'name': 'LLM_ENABLED', 'value': 'false'})
        for contract in (None, '', 'unknown-contract', True):
            with self.subTest(contract=contract):
                m = self.manifest()
                if contract is None:
                    del m['llm_disable_contract']
                else:
                    m['llm_disable_contract'] = contract
                self.assertEqual(self.api.sources_match(m), (True, False))

    def test_each_optional_disable_flag_is_a_veto_not_a_key_override(self):
        for name in ('LLM_ENABLED', 'OPENAI_ENABLED'):
            for value in ('true', '1', '', ' false ', None, False):
                with self.subTest(name=name, value=value):
                    containers = copy.deepcopy(self.definitions['ai:4'])
                    containers[0]['environment'].append({'name': name, 'value': value})
                    self.assertFalse(llm_credentials_absent(containers))
            containers = copy.deepcopy(self.definitions['ai:4'])
            containers[0]['environment'].append({'name': name, 'value': 'FALSE'})
            self.assertTrue(llm_credentials_absent(containers))
            containers[0]['environment'].append({'name': 'OPENAI_API_KEY', 'value': ''})
            self.assertFalse(llm_credentials_absent(containers))

    def test_credentials_empty_keys_paths_and_unknown_llm_controls_fail_closed(self):
        for name in ('OPENAI_API_KEY', 'openai_api_key', 'OPENAI_API_KEY_FILE',
                     'LLM_API_TOKEN', 'LLM_CREDENTIALS', 'ENABLE_OPENAI', 'LLM_PROVIDER'):
            for value in ('', 'synthetic-placeholder'):
                with self.subTest(name=name, empty=not value):
                    self.definitions['ai:4'][0]['environment'] = [{'name': name, 'value': value}]
                    self.assertEqual(self.api.sources_match(self.manifest()), (True, False))

    def test_only_reviewed_noncredential_options_are_allowed(self):
        containers = copy.deepcopy(self.definitions['ai:4'])
        containers[0]['environment'] += [{'name': 'OPENAI_MODEL', 'value': 'model'},
                                         {'name': 'LLM_TIMEOUT_SEC', 'value': '10'}]
        self.assertTrue(llm_credentials_absent(containers))

    def test_secret_name_or_reference_cannot_supply_a_provider_credential(self):
        for name, reference in [('OPENAI_API_KEY', 'opaque'), ('LLM_CONFIG', 'opaque'),
                                ('OPAQUE_CONFIG', 'secrets/openai-key'),
                                ('OPAQUE_CONFIG', 'parameters/llm-config')]:
            with self.subTest(name=name, reference=reference):
                self.definitions['ai:4'][0]['secrets'] = [{'name': name, 'valueFrom': reference}]
                self.assertEqual(self.api.sources_match(self.manifest()), (True, False))

    def test_environment_files_are_unverified_even_when_flags_are_false(self):
        for td in self.definitions:
            with self.subTest(td=td):
                container = self.definitions[td][0]
                container['environmentFiles'] = [{'type': 's3', 'value': 'arn:test:environment'}]
                self.assertEqual(self.api.sources_match(self.manifest()), (True, False))
                del container['environmentFiles']

    def test_every_service_and_sidecar_is_checked(self):
        for td in self.definitions:
            with self.subTest(td=td):
                sidecar = {'name': 'sidecar', 'environment': [{'name': 'OPENAI_API_KEY', 'value': ''}]}
                self.definitions[td].append(sidecar)
                self.assertEqual(self.api.sources_match(self.manifest()), (True, False))
                self.definitions[td].pop()

    def test_source_drift_invalidates_llm_proof_too(self):
        m = self.manifest()
        self.definitions['ai:4'][0]['image'] = 'ai:other-source'
        self.assertEqual(self.api.sources_match(m), (False, False))

    def test_incomplete_manifest_or_foreign_task_definition_is_rejected(self):
        m = self.manifest()
        del m['service_definitions']['server']
        self.assertEqual(self.api.sources_match(m), (False, False))
        self.ecs.describe_services.side_effect = None
        self.ecs.describe_services.return_value = {'services': [{'taskDefinition': 'ai:other'}]}
        self.assertEqual(self.api.sources_match(self.manifest()), (False, False))

    def test_missing_or_malformed_container_evidence_is_rejected(self):
        for containers in ([], None, [None], [{'environment': None}], [{'secrets': {}}],
                           [{'environmentFiles': None}], [{'environmentFiles': {}}],
                           [{'environment': [{}]}], [{'secrets': [{'name': 'DB_PASSWORD'}]}]):
            with self.subTest(containers=containers):
                self.assertFalse(llm_credentials_absent(containers))


if __name__ == '__main__':
    unittest.main()

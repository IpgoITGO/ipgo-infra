import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from d0_environment_gate import validate_environment


class WorkflowTest(unittest.TestCase):
    def test_infra_environment_requires_review_self_review_denial_and_exact_dev(self):
        env = {'protection_rules': [{'type':'required_reviewers','reviewers':[{'id':1}], 'prevent_self_review':True}], 'deployment_branch_policy':{'custom_branch_policies':True,'protected_branches':False}}
        validate_environment(env, {'branch_policies':[{'name':'dev','type':'branch'}]})
        for branches in [[], [{'name':'*'}], [{'name':'main'}], [{'name':'dev','type':'tag'}]]:
            with self.assertRaises(ValueError):
                validate_environment(env, {'branch_policies':branches})
        env['protection_rules'][0]['prevent_self_review']=False
        with self.assertRaises(ValueError):
            validate_environment(env, {'branch_policies':[{'name':'dev'}]})

    def test_manual_only_mutations_and_each_oidc_job_has_protection_check(self):
        text=(ROOT/'.github/workflows/d0-infrastructure.yml').read_text()
        self.assertIn('  workflow_dispatch:',text)
        self.assertNotIn('  push:',text)
        self.assertNotIn('  pull_request',text)
        self.assertEqual(3,text.count('id-token: write'))
        self.assertEqual(3,text.count('run: python3 scripts/d0_environment_gate.py'))
        self.assertEqual(3,text.count('      actions: read'))
        for job in ['publish','terraform','install']:
            part=text.split('  '+job+':',1)[1].split('\n  '+({'publish':'terraform','terraform':'install','install':'unused'}[job])+':')[0]
            self.assertLess(part.index('Verify protected Infra'),part.index('uses: aws-actions/configure-aws-credentials'))
            self.assertIn('environment: dev',part)

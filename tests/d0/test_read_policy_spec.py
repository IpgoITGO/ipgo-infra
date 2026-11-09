import json
import unittest
from pathlib import Path
from string import Template

ROOT=Path(__file__).resolve().parents[2]


class ReadPolicySpecTest(unittest.TestCase):
    def test_exact_six_read_actions_and_three_fixed_resources_without_other_grants(self):
        raw=(ROOT/'docs/permissions/d0-iam-preflight-read.json.template').read_text()
        arn='arn:aws:iam::123456789012:role/ipgo-github-terraform-apply'
        p=json.loads(Template(raw).substitute(infra_apply_role_arn=arn))
        self.assertEqual({'Version','Statement'},set(p))
        self.assertEqual('2012-10-17',p['Version'])
        self.assertEqual(2,len(p['Statement']))
        a,b=p['Statement']
        for s in [a,b]:
            self.assertEqual({'Sid','Effect','Action','Resource'},set(s))
            self.assertEqual('Allow',s['Effect'])
        self.assertEqual({'iam:GetRole','iam:GetRolePolicy','iam:ListRolePolicies','iam:ListAttachedRolePolicies'},set(a['Action']))
        self.assertEqual(arn,a['Resource'])
        self.assertEqual({'iam:GetPolicy','iam:GetPolicyVersion'},set(b['Action']))
        self.assertEqual({'arn:aws:iam::aws:policy/PowerUserAccess','arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy'},set(b['Resource']))
        self.assertNotIn('*',raw)

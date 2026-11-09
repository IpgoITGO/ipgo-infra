import copy
import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).resolve().parents[2]/'scripts/d0_plan_guard.py'
spec=importlib.util.spec_from_file_location('d0_guard',p)
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)


def entry(name='aws_iam_role.execution'):
    kind,field,value=guard.RESOURCES[name]
    return {'address':'module.d0[0].'+name,'type':kind,'change':{'actions':['create'],'before':None,
            'after':{field:value} if field else {}}}


class PlanTest(unittest.TestCase):
    def test_only_new_d0_resources_allowed_and_digest_binds_values(self):
        plan={'variables':{'configuration':{'value':'reviewed-metadata'}},'resource_changes':[entry()]}
        result=guard.review(plan)
        self.assertEqual(1,result['count'])
        other=copy.deepcopy(plan);other['variables']['configuration']['value']='changed'
        self.assertNotEqual(result['planSha256'],guard.review(other)['planSha256'])

    def test_existing_role_secret_deletion_replacement_and_import_rejected(self):
        for item in [
            dict(entry(),address='module.identity.aws_iam_role.nas_readonly'),
            dict(entry(),address='module.d0[0].aws_iam_role.unknown'),
            dict(entry(),type='aws_rds_cluster'),
            dict(entry(),change={'actions':['update'],'before':{},'after':{}}),
            dict(entry(),change={'actions':['delete','create'],'before':{},'after':{}}),
            dict(entry(),change={'actions':['delete'],'before':{},'after':None}),
            dict(entry(),change={'actions':['create'],'before':None,'after':{'name':'admin'}}),
            dict(entry(),change={'actions':['create'],'before':None,'after':{'name':'ipgo-dev-d0-execution'},'importing':{'id':'old'}})
        ]:
            with self.subTest(item=item),self.assertRaises(ValueError):
                guard.review({'resource_changes':[item]})
        secret=entry('aws_secretsmanager_secret.d0');secret['change']['actions']=['delete']
        with self.assertRaises(ValueError):guard.review({'resource_changes':[secret]},revoke=True)

    def test_runtime_revoke_is_exact_and_preserves_data_and_execution_role(self):
        item=entry('aws_iam_role.runner[0]');item['change']={'actions':['delete'],'before':{},'after':None}
        with self.assertRaises(ValueError):guard.review({'resource_changes':[item]})
        self.assertEqual(1,guard.review({'resource_changes':[item]},revoke=True)['count'])

    def test_manual_sha_account_config_and_reviewed_plan_required(self):
        import json
        env={'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/dev','GITHUB_RUN_ATTEMPT':'1',
             'EXPECTED_SHA':'a'*40,'GITHUB_SHA':'a'*40,'D0_INFRA_ENABLED':'true','OPERATION':'plan',
             'CONFIRMATION':'PLAN_D0','AWS_ACCOUNT_ID':'123456789012','TF_STATE_BUCKET':'test-state-bucket'}
        cfg={key:'reviewed' for key in guard.CONFIG};cfg['account_id']='123456789012'
        env['D0_TERRAFORM_JSON']=json.dumps({'enabled':True,'runtime_enabled':False,'configuration':cfg})
        guard.validate_job(env)
        for key,value in [('GITHUB_EVENT_NAME','push'),('EXPECTED_SHA','b'*40),('D0_INFRA_ENABLED',''),
                          ('GITHUB_REF','refs/heads/main'),('GITHUB_RUN_ATTEMPT','2')]:
            with self.subTest(key=key),self.assertRaises(ValueError):guard.validate_job(dict(env,**{key:value}))
        with self.assertRaises(ValueError):guard.validate_job(dict(env,OPERATION='apply',CONFIRMATION='APPLY_D0'))
        with self.assertRaisesRegex(ValueError,'REVIEWED_IAM_REQUIRED'):
            guard.validate_job(dict(env,OPERATION='apply',CONFIRMATION='APPLY_D0',EXPECTED_PLAN_SHA256='a'*64))
        guard.validate_job(dict(env,OPERATION='apply',CONFIRMATION='APPLY_D0',EXPECTED_PLAN_SHA256='a'*64,EXPECTED_IAM_SNAPSHOT_SHA256='b'*64))
        guard.validate_job(dict(env,OPERATION='preflight',CONFIRMATION='PREFLIGHT_D0'))


if __name__=='__main__':unittest.main()

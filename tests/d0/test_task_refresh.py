import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from d0_plan_guard import review, TASKS, validate_job

IMAGE = '123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/ipgo-dev/database@sha256:'


def plan():
    changes=[]
    for key in sorted(TASKS):
        before={'family':'ipgo-dev-d0-'+('install' if key.endswith('install') else 'validation'),
                'cpu':'256','memory':'512','network_mode':'awsvpc','execution_role_arn':'fixed',
                'skip_destroy':True,'arn':'old','id':'old','revision':1,'arn_without_revision':'fixed',
                'container_definitions':json.dumps([{'name':'runner','image':IMAGE+'a'*64,
                  'command':['install' if key.endswith('install') else 'read-only'],
                  'secrets':[{'name':'PASSWORD','valueFrom':'fixed'}]}])}
        after=copy.deepcopy(before);after.update(skip_destroy=True,arn=None,id=None,revision=None)
        after['container_definitions']=after['container_definitions'].replace('a'*64,'b'*64)
        changes.append({'address':'module.d0[0].'+key,'type':'aws_ecs_task_definition',
                        'change':{'actions':['create','delete'],'before':before,'after':after,
                                  'after_unknown':{'arn':True,'revision':True,'id':True}}})
    return {'resource_changes':changes}


class TaskRefreshTest(unittest.TestCase):
    def check(self,p):return review(p,refresh=True,image_uri=IMAGE+'b'*64)

    def test_exact_two_image_refresh_and_reverse_digest_are_allowed(self):
        p=plan();self.assertEqual(2,self.check(p)['count'])
        for item in p['resource_changes']:
            c=item['change'];c['before'],c['after']=c['after'],c['before']
            c['after']['skip_destroy']=True
        self.assertEqual(2,review(p,refresh=True,image_uri=IMAGE+'a'*64)['count'])

    def test_protect_is_metadata_only_two_updates_before_image_replacement(self):
        p=plan()
        for item in p['resource_changes']:
            c=item['change'];c['before']['skip_destroy']=False
            c['after']=copy.deepcopy(c['before']);c['after']['skip_destroy']=True
            c['after_unknown']={};c['actions']=['update']
        self.assertEqual(2,review(p,protect=True,image_uri=IMAGE+'a'*64)['count'])
        p['resource_changes'][0]['change']['after']['cpu']='512'
        with self.assertRaises(ValueError):review(p,protect=True,image_uri=IMAGE+'a'*64)

    def test_other_attributes_unknown_unsafe_order_or_only_one_task_are_denied(self):
        for mutate in [
            lambda p:p['resource_changes'].pop(),
            lambda p:p['resource_changes'][0]['change']['after'].update(cpu='512'),
            lambda p:p['resource_changes'][0]['change']['after'].update(skip_destroy=False),
            lambda p:p['resource_changes'][0]['change']['before'].update(skip_destroy=False),
            lambda p:p['resource_changes'][0]['change'].update(actions=['delete','create']),
            lambda p:p['resource_changes'][0]['change']['after_unknown'].update(task_role_arn=True),
            lambda p:p['resource_changes'][0].update(previous_address='outside'),
            lambda p:p['resource_changes'].append({'address':'outside','type':'aws_iam_role',
                'previous_address':'old','change':{'actions':['no-op']}}),
            lambda p:p.update(resource_drift=[{'change':{'actions':['update']}}]),
            lambda p:p['resource_changes'].append({'address':'module.d0[0].aws_iam_role.installer',
                'type':'aws_iam_role','change':{'actions':['update'],'before':{},'after':{}}}),
        ]:
            p=plan();mutate(p)
            with self.subTest(p=p),self.assertRaises(ValueError):self.check(p)

    def test_secret_command_image_account_or_other_container_change_is_denied(self):
        for field,value in [('command',['deactivate']),('secrets',[]),('image',IMAGE.replace('123456789012','999999999999')+'b'*64)]:
            p=plan();c=p['resource_changes'][0]['change'];containers=json.loads(c['after']['container_definitions'])
            containers[0][field]=value;c['after']['container_definitions']=json.dumps(containers)
            with self.subTest(field=field),self.assertRaises(ValueError):self.check(p)
        with self.assertRaises(ValueError):review(plan())
        with self.assertRaises(ValueError):review(plan(),refresh=True,revoke=True,image_uri=IMAGE+'b'*64)
        with self.assertRaises(ValueError):review(plan(),refresh=True,image_uri=IMAGE+'c'*64)

    def test_mode_needs_explicit_confirmation_and_runtime_stays_off(self):
        from test_plan_guard import guard
        env={'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/dev','GITHUB_RUN_ATTEMPT':'1',
             'EXPECTED_SHA':'a'*40,'GITHUB_SHA':'a'*40,'D0_INFRA_ENABLED':'true','OPERATION':'plan',
             'CONFIRMATION':'PLAN_D0_TASK_REFRESH','REFRESH_TASKS':'true',
             'AWS_ACCOUNT_ID':'123456789012','TF_STATE_BUCKET':'test-state-bucket'}
        config={k:'reviewed' for k in guard.CONFIG};config['account_id']='123456789012'
        cfg={'enabled':True,'runtime_enabled':False,'configuration':config}
        env['D0_TERRAFORM_JSON']=json.dumps(cfg);validate_job(env)
        for changes in [{'CONFIRMATION':'PLAN_D0'},{'REVOKE_RUNTIME':'true'}]:
            with self.assertRaises(ValueError):validate_job(dict(env,**changes))
        protected=dict(env,REFRESH_TASKS='false',PROTECT_TASKS='true',CONFIRMATION='PLAN_D0_TASK_PROTECT')
        validate_job(protected)
        with self.assertRaises(ValueError):validate_job(dict(protected,REFRESH_TASKS='true'))
        with self.assertRaises(ValueError):validate_job(dict(protected,CONFIRMATION='PLAN_D0_TASK_REFRESH'))
        cfg['runtime_enabled']=True;env['D0_TERRAFORM_JSON']=json.dumps(cfg)
        with self.assertRaises(ValueError):validate_job(env)

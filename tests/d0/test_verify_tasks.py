import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from d0_verify_tasks import revisions,verify
from test_task_refresh import plan,IMAGE


class Ecs:
    def __init__(self,old,new_image):
        self.rows={};self.calls=[]
        for t in old.values():
            self.rows[t['arn']]={'taskDefinitionArn':t['arn'],'status':'ACTIVE','containerDefinitions':[{'image':t['image']}]}
            new=t['arn'].rsplit(':',1)[0]+':2'
            self.rows[new]={'taskDefinitionArn':new,'status':'ACTIVE','containerDefinitions':[{'image':new_image}]}
    def describe_task_definition(self,**kw):
        self.calls.append(kw);return {'taskDefinition':self.rows[kw['taskDefinition']]}


def old():
    p=plan()
    for e in p['resource_changes']:
        family=e['change']['before']['family']
        e['change']['before']['arn']=f'arn:aws:ecs:ap-northeast-2:123456789012:task-definition/{family}:1'
    return revisions(p,'123456789012')


def outputs(previous,image=IMAGE+'b'*64):
    return {('installation' if name=='install' else 'runtime'):{'value':{'task_definition_arn':t['arn'].rsplit(':',1)[0]+':2','image_uri':image}}
            for name,t in previous.items()}


class VerifyTasksTest(unittest.TestCase):
    def test_old_and_new_active_before_after_and_protect_same_revision(self):
        previous=old();ecs=Ecs(previous,IMAGE+'b'*64)
        self.assertEqual(2,len(verify(ecs,previous)))
        self.assertEqual(2,len(verify(ecs,previous,outputs=outputs(previous),refresh=True,image_uri=IMAGE+'b'*64)))
        o=outputs(previous,IMAGE+'a'*64)
        for k in o:o[k]['value']['task_definition_arn']=o[k]['value']['task_definition_arn'].rsplit(':',1)[0]+':1'
        verify(ecs,previous,outputs=o,refresh=False,image_uri=IMAGE+'a'*64)

    def test_inactive_old_wrong_new_family_or_image_stops_verification(self):
        previous=old()
        for mutation in ['inactive','family','image','same-revision']:
            ecs=Ecs(previous,IMAGE+'b'*64);o=outputs(previous)
            if mutation=='inactive':ecs.rows[previous['install']['arn']]['status']='INACTIVE'
            if mutation=='family':o['installation']['value']['task_definition_arn']=previous['runtime']['arn']
            if mutation=='image':o['installation']['value']['image_uri']=IMAGE+'c'*64
            if mutation=='same-revision':o['installation']['value']['task_definition_arn']=previous['install']['arn']
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify(ecs,previous,outputs=o,refresh=True,image_uri=IMAGE+'b'*64)

    def test_partial_refresh_only_replaces_changed_slot_and_verifies_other_active(self):
        previous=old();previous['runtime']['image']=IMAGE+'b'*64
        ecs=Ecs(previous,IMAGE+'b'*64);o=outputs(previous)
        o['runtime']['value']['task_definition_arn']=previous['runtime']['arn']
        verify(ecs,previous,outputs=o,refresh=True,image_uri=IMAGE+'b'*64,replaced={'install'})
        o['runtime']['value']['task_definition_arn']=o['runtime']['value']['task_definition_arn'].rsplit(':',1)[0]+':2'
        with self.assertRaises(ValueError):verify(ecs,previous,outputs=o,refresh=True,image_uri=IMAGE+'b'*64,replaced={'install'})

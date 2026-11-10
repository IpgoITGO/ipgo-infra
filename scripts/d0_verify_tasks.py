"""승인된 두 D0 TD의 적용 전후 ACTIVE 확인. task/서비스/DB 쓰기 없음."""
import json
import os
import re
import sys
from pathlib import Path

from d0_plan_guard import require, review, TASKS


def revisions(plan, account):
    result={}
    for entry in plan['resource_changes']:
        key=entry['address'].removeprefix('module.d0[0].')
        if key not in TASKS:
            continue
        before=entry['change']['before']
        name=key.rsplit('.',1)[1]
        family='install' if name=='install' else 'validation'
        arn=before['arn']
        require(re.fullmatch(f'arn:aws:ecs:ap-northeast-2:{account}:task-definition/ipgo-dev-d0-{family}:[1-9][0-9]*',arn), 'OLD_TASK_ARN')
        result[name]={'arn':arn,'image':json.loads(before['container_definitions'])[0]['image']}
    require(set(result)=={'install','runtime'},'EXACT_TWO_TASKS_REQUIRED')
    return result


def verify(ecs, old, *, outputs=None, refresh=False, image_uri=None, replaced=None):
    replaced = set(old) if replaced is None and refresh else (replaced or set())
    observed={}
    for name,target in old.items():
        td=ecs.describe_task_definition(taskDefinition=target['arn'])['taskDefinition']
        require(td['taskDefinitionArn']==target['arn'] and td['status']=='ACTIVE'
                and len(td['containerDefinitions'])==1 and td['containerDefinitions'][0]['image']==target['image'], 'OLD_REVISION_NOT_ACTIVE')
        observed[name]={'before':target}
        if outputs is not None:
            cfg=outputs['installation' if name=='install' else 'runtime']['value']
            arn=cfg['task_definition_arn']
            prefix=target['arn'].rsplit(':',1)[0]+':'
            require(arn.startswith(prefix) and re.fullmatch('[1-9][0-9]*',arn[len(prefix):]), 'NEW_TASK_ARN')
            require((int(arn[len(prefix):]) > int(target['arn'].rsplit(':',1)[1])) if name in replaced else arn==target['arn'], 'REVISION_TRANSITION')
            current=ecs.describe_task_definition(taskDefinition=arn)['taskDefinition']
            require(current['taskDefinitionArn']==arn and current['status']=='ACTIVE'
                    and len(current['containerDefinitions'])==1
                    and current['containerDefinitions'][0]['image']==image_uri
                    and cfg['image_uri']==image_uri, 'NEW_REVISION_NOT_VERIFIED')
            observed[name]['after']={'arn':arn,'image':image_uri}
    return observed


def main():
    import boto3
    from botocore.config import Config
    from cryptography.hazmat.primitives import serialization
    from d0_plan_envelope import seal, PUBLIC_KEY
    from d0_iam_preflight import validate_snapshot
    phase=sys.argv[1]
    require(phase in ('before','after') and os.environ['OPERATION']=='apply','APPLY_PHASE_ONLY')
    protect=os.environ.get('PROTECT_TASKS')=='true'
    refresh=os.environ.get('REFRESH_TASKS')=='true'
    require(protect != refresh,'TASK_MODE_REQUIRED')
    root=Path(os.environ['RUNNER_TEMP'])
    cfg=json.loads(os.environ['D0_TERRAFORM_JSON'])
    plan=json.loads((root/'d0-plan.json').read_text())
    review_result=review(plan,protect=protect,refresh=refresh,image_uri=cfg['configuration']['image_uri'])
    require(review_result['planSha256']==os.environ['EXPECTED_PLAN_SHA256'],'PLAN_CHANGED')
    snapshot=json.loads((root/'d0-iam-snapshot.json').read_text())
    validate_snapshot(snapshot,os.environ,cfg)
    old=revisions(plan,os.environ['AWS_ACCOUNT_ID'])
    outputs=json.loads((root/'d0-outputs.json').read_text()) if phase=='after' else None
    sdk=Config(retries={'total_max_attempts':1},connect_timeout=5,read_timeout=20)
    observed=verify(boto3.client('ecs',region_name='ap-northeast-2',config=sdk),old,
                    outputs=outputs,refresh=refresh,image_uri=cfg['configuration']['image_uri'],
                    replaced={e['address'].rsplit('.',1)[1] for e in plan['resource_changes']
                              if e['change']['actions']==['create','delete']})
    context={'workflowSha':os.environ['GITHUB_SHA'],'runId':os.environ['GITHUB_RUN_ID'],
             'phase':phase,**review_result,'iamSnapshotSha256':snapshot['iamSnapshotSha256']}
    key=serialization.load_pem_public_key(PUBLIC_KEY.read_bytes())
    envelope=seal(json.dumps(observed,sort_keys=True).encode(),context,key)
    with open(root/f'd0-task-revisions-{phase}-envelope.json','x',opener=lambda p,f:os.open(p,f,0o600)) as file:
        json.dump(envelope,file,sort_keys=True)
    print('D0 두 TD ACTIVE/이미지 검증 성공. ARN·설정은 암호화 근거에만 보존합니다.')


if __name__=='__main__':
    try:main()
    except Exception:
        print('D0_TASK_REVISION_VERIFICATION_FAILED: 추가 적용/DB 설치/D0를 중단하고 보호된 state와 이전 revision을 확인하세요.')
        raise SystemExit(1) from None

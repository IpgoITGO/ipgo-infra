"""D0 독립 state의 초기 생성·정확 TD 보호/갱신만 검토. plan 값/내부 ARN은 출력하지 않는다."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

RESOURCES = {
    'aws_secretsmanager_secret.d0': ('aws_secretsmanager_secret', 'name', '/ipgo/dev/d0-bootstrap'),
    'aws_cloudwatch_log_group.d0': ('aws_cloudwatch_log_group', 'name', '/ipgo/dev/d0-validation'),
    'aws_iam_role.execution': ('aws_iam_role', 'name', 'ipgo-dev-d0-execution'),
    'aws_iam_role.installer': ('aws_iam_role', 'name', 'ipgo-dev-d0-install-task'),
    'aws_iam_role.runner[0]': ('aws_iam_role', 'name', 'ipgo-dev-d0-runner-oidc'),
    'aws_iam_role_policy.execution': ('aws_iam_role_policy', None, None),
    'aws_iam_role_policy.installer': ('aws_iam_role_policy', None, None),
    'aws_iam_role_policy.runner[0]': ('aws_iam_role_policy', None, None),
    'aws_ecs_task_definition.runtime': ('aws_ecs_task_definition', 'family', 'ipgo-dev-d0-validation'),
    'aws_ecs_task_definition.install': ('aws_ecs_task_definition', 'family', 'ipgo-dev-d0-install'),
}
REVOKE = {'aws_iam_role.runner[0]', 'aws_iam_role_policy.runner[0]'}
CONFIG = {'account_id','image_uri','bootstrap_execution_role_arn','master_secret_arn','installation_log_group',
          'db_host','db_name','subnet_ids','security_group_ids'}


def require(value, code):
    if not value:
        raise ValueError(code)


def validate_job(env):
    require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and env.get('GITHUB_REF') == 'refs/heads/dev'
            and env.get('GITHUB_RUN_ATTEMPT') == '1', 'MANUAL_DEV_ONLY')
    require(re.fullmatch('[a-f0-9]{40}',env.get('EXPECTED_SHA',''))
            and env['EXPECTED_SHA'] == env.get('GITHUB_SHA'), 'APPROVED_SHA')
    require(env.get('D0_INFRA_ENABLED') == 'true', 'D0_INFRA_DISABLED')
    operation = env.get('OPERATION')
    require(operation in ('preflight','plan','apply'), 'OPERATION')
    revoke = env.get('REVOKE_RUNTIME') == 'true'
    refresh = env.get('REFRESH_TASKS') == 'true'
    protect = env.get('PROTECT_TASKS') == 'true'
    require(sum((revoke, refresh, protect)) <= 1, 'CONFLICTING_MODES')
    expected_confirmation = operation.upper() + ('_D0_TASK_PROTECT' if protect else '_D0_TASK_REFRESH' if refresh else '_D0_REVOKE' if revoke else '_D0')
    require(env.get('CONFIRMATION') == expected_confirmation, 'CONFIRMATION')
    cfg = json.loads(env.get('D0_TERRAFORM_JSON','{}'))
    require(set(cfg) == {'enabled','runtime_enabled','configuration'} and cfg['enabled'] is True
            and type(cfg['runtime_enabled']) is bool and set(cfg['configuration']) == CONFIG,
            'CONFIGURATION_FIELDS')
    require(not revoke or cfg['runtime_enabled'] is False, 'REVOKE_RUNTIME_CONFIG')
    require(not (refresh or protect) or cfg['runtime_enabled'] is False, 'REFRESH_RUNTIME_MUST_STAY_DISABLED')
    require(cfg['configuration']['account_id'] == env.get('AWS_ACCOUNT_ID')
            and re.fullmatch('[0-9]{12}', env.get('AWS_ACCOUNT_ID','')), 'ACCOUNT_ID')
    require(re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',env.get('TF_STATE_BUCKET','')), 'STATE_BUCKET')
    if operation == 'apply':
        require(re.fullmatch('[a-f0-9]{64}',env.get('EXPECTED_PLAN_SHA256','')), 'REVIEWED_PLAN_REQUIRED')
        require(re.fullmatch('[a-f0-9]{64}',env.get('EXPECTED_IAM_SNAPSHOT_SHA256','')), 'REVIEWED_IAM_REQUIRED')
    return cfg


TASKS = {'aws_ecs_task_definition.install', 'aws_ecs_task_definition.runtime'}
COMPUTED = {'id', 'arn', 'arn_without_revision', 'revision'}


def review_task_refresh(entry, family):
    change = entry['change']
    before, after = change.get('before'), change.get('after')
    require(isinstance(before, dict) and isinstance(after, dict), 'TASK_VALUES_REQUIRED')
    require(before.get('family') == after.get('family') == family, 'TASK_FAMILY_CHANGED')
    require(not entry.get('previous_address') and not entry.get('deposed'), 'TASK_STATE_MOVE')
    require(before.get('skip_destroy') is True and after.get('skip_destroy') is True, 'OLD_REVISION_MUST_BE_PRESERVED')
    unknown = change.get('after_unknown', {})
    require(not any(v for k,v in unknown.items() if k not in COMPUTED), 'UNKNOWN_TASK_ATTRIBUTES')
    ignored = COMPUTED | {'container_definitions', 'skip_destroy'}
    require({k:v for k,v in before.items() if k not in ignored} ==
            {k:v for k,v in after.items() if k not in ignored}, 'TASK_ATTRIBUTE_CHANGED')
    old = json.loads(before['container_definitions'])
    new = json.loads(after['container_definitions'])
    require(len(old) == len(new) == 1 and old[0].get('name') == new[0].get('name') == 'runner', 'TASK_CONTAINER_BOUNDARY')
    old_image, new_image = old[0].pop('image'), new[0].pop('image')
    require(old == new, 'TASK_CONTAINER_ATTRIBUTE_CHANGED')
    pattern = r'([0-9]{12}[.]dkr[.]ecr[.]ap-northeast-2[.]amazonaws[.]com/ipgo-dev/database)@sha256:[a-f0-9]{64}'
    a, b = re.fullmatch(pattern, old_image), re.fullmatch(pattern, new_image)
    require(a and b and a[1] == b[1] and old_image != new_image, 'IMMUTABLE_SAME_REPOSITORY_IMAGE_REQUIRED')
    return new_image


def review_task_protect(entry, family):
    change = entry['change']
    before, after = change.get('before'), change.get('after')
    require(isinstance(before, dict) and isinstance(after, dict), 'TASK_VALUES_REQUIRED')
    require(before.get('family') == after.get('family') == family, 'TASK_FAMILY_CHANGED')
    require(before.get('skip_destroy') is False and after.get('skip_destroy') is True, 'PROTECT_FALSE_TO_TRUE_ONLY')
    require(not entry.get('previous_address') and not entry.get('deposed'), 'TASK_STATE_MOVE')
    require(not any(change.get('after_unknown', {}).values()), 'UNKNOWN_TASK_ATTRIBUTES')
    require({k:v for k,v in before.items() if k != 'skip_destroy'} ==
            {k:v for k,v in after.items() if k != 'skip_destroy'}, 'PROTECT_ATTRIBUTE_CHANGED')
    containers = json.loads(after['container_definitions'])
    require(len(containers) == 1 and containers[0].get('name') == 'runner', 'TASK_CONTAINER_BOUNDARY')
    return containers[0]['image']


def review(plan, *, revoke=False, refresh=False, protect=False, image_uri=None):
    require(sum((revoke, refresh, protect)) <= 1, 'CONFLICTING_MODES')
    summary = []
    images = []
    if refresh or protect:
        require(not any(x.get('change', {}).get('actions') != ['no-op'] for x in plan.get('resource_drift', [])), 'REFRESH_DRIFT')
    for entry in plan.get('resource_changes',[]):
        require(not entry.get('previous_address') and not entry.get('deposed')
                and not entry['change'].get('importing'), 'STATE_MOVE_OR_IMPORT')
        if entry['change']['actions'] == ['no-op']:
            continue
        address = entry['address']
        prefix = 'module.d0[0].'
        require(address.startswith(prefix), 'OUTSIDE_D0_STATE_SCOPE')
        key = address[len(prefix):]
        require(key in RESOURCES, 'UNREVIEWED_RESOURCE')
        kind, field, expected = RESOURCES[key]
        require(entry.get('type') == kind and not entry['change'].get('importing'), 'RESOURCE_TYPE_OR_IMPORT')
        actions = entry['change']['actions']
        if protect:
            require(key in TASKS and actions == ['update'], 'TASK_PROTECT_SCOPE')
            images.append(review_task_protect(entry, expected))
        elif refresh:
            require(key in TASKS and actions == ['create', 'delete'], 'TASK_REFRESH_SCOPE')
            images.append(review_task_refresh(entry, expected))
        elif actions == ['delete']:
            require(revoke and key in REVOKE, 'DELETE_NOT_APPROVED')
        else:
            require(actions == ['create'] and entry['change'].get('before') is None, 'UPDATE_OR_REPLACE_NOT_APPROVED')
            after = entry['change'].get('after') or {}
            require(field is None or after.get(field) == expected, 'PHYSICAL_NAME_CHANGED')
        summary.append({'address':address,'actions':actions})
    if refresh or protect:
        require({x['address'].split('module.d0[0].',1)[1] for x in summary} == TASKS
                and len(summary) == 2, 'EXACT_TWO_TASKS_REQUIRED')
        require(len(set(images)) == 1 and images[0] == image_uri, 'REFRESH_IMAGE_CONFIGURATION')
    # 외부 API·현재 시각 등 비결정적 외곽 필드는 제외. 값은 출력하지 않지만 승인 digest에는 포함.
    material = {'mode': 'task-protect' if protect else 'task-refresh' if refresh else 'revoke' if revoke else 'create', 'variables':plan.get('variables',{}),'resource_changes':plan.get('resource_changes',[])}
    digest = hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'planSha256':digest,'changes':summary,'count':len(summary)}


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'gate':
            config = validate_job(os.environ)
            with open(Path(os.environ['RUNNER_TEMP'])/'d0.tfvars.json','w',
                      opener=lambda p,flags:os.open(p,flags,0o600)) as file:
                json.dump(config,file)
            print('D0 Infra 입력 검사 성공. 설정 값 출력 없음.')
        elif sys.argv[1] == 'review':
            from d0_iam_preflight import validate_snapshot, check_plan
            config = validate_job(os.environ)
            snapshot = json.loads((Path(os.environ['RUNNER_TEMP'])/'d0-iam-snapshot.json').read_text())
            validate_snapshot(snapshot, os.environ, config)
            plan = json.loads(Path(sys.argv[2]).read_text())
            check_plan(snapshot, plan)
            result = review(plan,revoke=os.environ.get('REVOKE_RUNTIME')=='true',
                            refresh=os.environ.get('REFRESH_TASKS')=='true',
                            protect=os.environ.get('PROTECT_TASKS')=='true',
                            image_uri=config['configuration']['image_uri'])
            if os.environ.get('OPERATION') == 'apply':
                require(result['planSha256'] == os.environ.get('EXPECTED_PLAN_SHA256'), 'PLAN_CHANGED')
            print(json.dumps(result,sort_keys=True))
        else:
            raise ValueError('MODE')
    except Exception:
        print('D0 Infra 승인/plan 검사 실패. 적용하지 않습니다.')
        raise SystemExit(1) from None

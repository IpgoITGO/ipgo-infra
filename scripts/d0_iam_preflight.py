"""기존 Infra OIDC의 읽기 전용 IAM 증거. 실패 원문도 암호화하고 쓰기 전 중단한다."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote


class PreflightError(ValueError):
    pass


def require(value, code):
    if not value:
        raise PreflightError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def document(value):
    if isinstance(value, str):
        value = json.loads(unquote(value))
    require(isinstance(value, dict) and 'Statement' in value, 'POLICY_DOCUMENT_INCOMPLETE')
    return value


def targets(configuration, caller_role_arn, *, install=False, include_runner=False):
    account = configuration['account_id']
    prefix = f'arn:aws:iam::{account}:role/'
    require(re.fullmatch('[0-9]{12}', account), 'ACCOUNT')
    require(caller_role_arn == prefix + 'ipgo-github-terraform-apply', 'CALLER_ROLE_BOUNDARY')
    require(configuration['bootstrap_execution_role_arn'] == prefix + 'ipgo-dev-database-bootstrap-execution',
            'BOOTSTRAP_ROLE_BOUNDARY')
    roles = [
        {'alias': 'caller', 'arn': caller_role_arn, 'optional': False},
        {'alias': 'bootstrap', 'arn': configuration['bootstrap_execution_role_arn'], 'optional': False},
        {'alias': 'execution', 'arn': prefix + 'ipgo-dev-d0-execution', 'optional': not install},
        {'alias': 'installer', 'arn': prefix + 'ipgo-dev-d0-install-task', 'optional': not install},
    ]
    if include_runner:
        roles.append({'alias': 'runner', 'arn': prefix + 'ipgo-dev-d0-runner-oidc', 'optional': True})
    return roles


def fingerprint(snapshot):
    # 세션 이름/시각/runId가 달라도 같은 SHA·설정·권한이면 같은 검토 fingerprint다.
    return digest({k: snapshot[k] for k in ('schemaVersion', 'accountId', 'callerRoleArn',
                   'sourceSha', 'configurationSha256', 'roles', 'managedPolicies')})


def collect(sts, iam, configuration, caller_role_arn, source_sha, configuration_hash,
            *, run_id, operation, install=False, include_runner=False):
    role_targets = targets(configuration, caller_role_arn, install=install, include_runner=include_runner)
    require(re.fullmatch('[a-f0-9]{40}', source_sha), 'SOURCE_SHA')
    result = {'schemaVersion': 1, 'accountId': configuration['account_id'], 'callerRoleArn': caller_role_arn,
              'sourceSha': source_sha, 'configurationSha256': configuration_hash,
              'runId': str(run_id), 'operation': operation, 'observedAt': datetime.now(timezone.utc).isoformat(),
              'success': False, 'roles': {}, 'managedPolicies': {}, 'calls': []}
    active = {'api': 'sts:GetCallerIdentity', 'target': 'caller'}

    def call(client, api, alias, **params):
        active.update(api=api, target=alias)
        result['calls'].append({'api': api, 'target': alias, 'parameters': params})
        return getattr(client, re.sub(r'(?<!^)(?=[A-Z])', '_', api.split(':')[1]).lower())(**params)

    def pages(api, alias, field, **params):
        values, seen = [], set()
        for _ in range(100):
            response = call(iam, api, alias, **params)
            require(isinstance(response.get(field), list), 'PAGE_INCOMPLETE')
            values.extend(response[field])
            if not response.get('IsTruncated', False):
                return values
            marker = response.get('Marker')
            require(isinstance(marker, str) and marker and marker not in seen, 'PAGE_MARKER_INCOMPLETE')
            seen.add(marker)
            params['Marker'] = marker
        raise PreflightError('PAGE_LIMIT')

    def managed(arn):
        if arn in result['managedPolicies']:
            return
        require(re.fullmatch(r'arn:aws:iam::(?:aws|' + configuration['account_id'] + r'):policy/[A-Za-z0-9+=,.@_/-]+', arn), 'POLICY_ARN')
        p = call(iam, 'iam:GetPolicy', 'managed-policy', PolicyArn=arn)['Policy']
        require(p.get('Arn') == arn and re.fullmatch('v[1-9][0-9]*', p.get('DefaultVersionId', '')), 'POLICY_METADATA')
        version = call(iam, 'iam:GetPolicyVersion', 'managed-policy', PolicyArn=arn,
                       VersionId=p['DefaultVersionId'])['PolicyVersion']
        require(version.get('VersionId') == p['DefaultVersionId'] and version.get('IsDefaultVersion') is True,
                'POLICY_DEFAULT_CHANGED')
        result['managedPolicies'][arn] = {'versionId': version['VersionId'], 'document': document(version['Document'])}

    try:
        identity = call(sts, 'sts:GetCallerIdentity', 'caller')
        account = configuration['account_id']
        require(identity.get('Account') == account and
                identity.get('Arn', '').startswith(f'arn:aws:sts::{account}:assumed-role/ipgo-github-terraform-apply/'),
                'ACTUAL_CALLER_MISMATCH')
        result['callerIdentity'] = {k: identity.get(k) for k in ('Account', 'Arn', 'UserId')}
        for target in role_targets:
            alias, arn = target['alias'], target['arn']
            name = arn.rsplit('/', 1)[1]
            try:
                role = call(iam, 'iam:GetRole', alias, RoleName=name)['Role']
            except Exception as error:
                code = getattr(error, 'response', {}).get('Error', {}).get('Code')
                if code == 'NoSuchEntity' and target['optional']:
                    result['roles'][alias] = {'arn': arn, 'exists': False}
                    continue
                raise
            require(role.get('Arn') == arn and role.get('RoleName') == name and role.get('RoleId'), 'ROLE_METADATA')
            current = {'arn': arn, 'exists': True, 'roleId': role['RoleId'],
                       'trust': document(role['AssumeRolePolicyDocument']),
                       'maxSessionDuration': role.get('MaxSessionDuration'), 'inline': {}, 'attached': []}
            result['roles'][alias] = current
            inline = pages('iam:ListRolePolicies', alias, 'PolicyNames', RoleName=name)
            require(all(isinstance(x, str) and re.fullmatch(r'[A-Za-z0-9+=,.@_-]{1,128}', x) for x in inline)
                    and len(inline) == len(set(inline)), 'INLINE_NAMES')
            for policy_name in sorted(inline):
                p = call(iam, 'iam:GetRolePolicy', alias, RoleName=name, PolicyName=policy_name)
                require(p.get('RoleName') == name and p.get('PolicyName') == policy_name, 'INLINE_METADATA')
                current['inline'][policy_name] = document(p['PolicyDocument'])
            attached = pages('iam:ListAttachedRolePolicies', alias, 'AttachedPolicies', RoleName=name)
            arns = [p['PolicyArn'] for p in attached]
            require(len(arns) == len(set(arns)), 'ATTACHED_DUPLICATE')
            current['attached'] = sorted(arns)
            for policy_arn in current['attached']:
                managed(policy_arn)
            boundary = role.get('PermissionsBoundary')
            if boundary:
                require(boundary.get('PermissionsBoundaryType') == 'Policy', 'BOUNDARY_TYPE')
                current['permissionsBoundary'] = boundary['PermissionsBoundaryArn']
                managed(boundary['PermissionsBoundaryArn'])
        result['success'] = True
        result['iamSnapshotSha256'] = fingerprint(result)
    except Exception as error:
        code = getattr(error, 'response', {}).get('Error', {}).get('Code') or (
            str(error) if isinstance(error, PreflightError) else type(error).__name__)
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code):
            code = 'UNKNOWN_ERROR'
        result['failure'] = {**active, 'code': code}
    return result


def validate_snapshot(snapshot, env, configuration):
    require(snapshot.get('success') is True and snapshot.get('schemaVersion') == 1, 'IAM_PREFLIGHT_NOT_COMPLETE')
    require(snapshot['accountId'] == env['AWS_ACCOUNT_ID'] and snapshot['sourceSha'] == env['GITHUB_SHA']
            and snapshot['runId'] == env['GITHUB_RUN_ID'] and snapshot['operation'] == env['OPERATION']
            and snapshot['callerRoleArn'] == env['AWS_APPLY_ROLE_ARN']
            and snapshot['configurationSha256'] == digest(configuration), 'IAM_SNAPSHOT_CONTEXT')
    require(snapshot.get('iamSnapshotSha256') == fingerprint(snapshot), 'IAM_SNAPSHOT_INTEGRITY')
    required = targets(configuration['configuration'], env['AWS_APPLY_ROLE_ARN'],
                       install=env['OPERATION']=='install', include_runner=configuration.get('runtime_enabled') is True
                       or env.get('REVOKE_RUNTIME')=='true')
    require(set(snapshot['roles']) == {r['alias'] for r in required}, 'IAM_SNAPSHOT_TARGETS')
    require(all(snapshot['roles'][r['alias']]['arn']==r['arn'] and
                (r['optional'] or snapshot['roles'][r['alias']]['exists'] is True) for r in required),
            'IAM_SNAPSHOT_REQUIRED_ROLES')
    if env.get('OPERATION') in ('apply', 'install'):
        require(snapshot['iamSnapshotSha256'] == env.get('EXPECTED_IAM_SNAPSHOT_SHA256'), 'IAM_SNAPSHOT_CHANGED')


def check_plan(snapshot, plan):
    observed = {r['arn'].rsplit('/', 1)[1]: r for r in snapshot['roles'].values()}
    for change in plan.get('resource_changes', []):
        if change.get('type') == 'aws_iam_role' and 'create' in change['change']['actions']:
            name = (change['change'].get('after') or {}).get('name')
            require(name in observed and observed[name]['exists'] is False, 'IAM_ROLE_CREATE_COLLISION')


def persist(snapshot, directory, public_key=None):
    from cryptography.hazmat.primitives import serialization
    from d0_plan_envelope import PUBLIC_KEY, seal
    directory = Path(directory)
    raw = canonical(snapshot)
    with open(directory / 'd0-iam-snapshot.json', 'xb', opener=lambda p, f: os.open(p, f, 0o600)) as output:
        output.write(raw)
    public_key = public_key or serialization.load_pem_public_key(PUBLIC_KEY.read_bytes())
    context = {'kind': 'D0_IAM_PREFLIGHT', 'workflowSha': snapshot['sourceSha'], 'runId': snapshot['runId'],
               'success': snapshot['success'], 'iamSnapshotSha256': snapshot.get('iamSnapshotSha256')}
    envelope = seal(raw, context, public_key)
    with open(directory / 'd0-iam-snapshot-envelope.json', 'xb', opener=lambda p, f: os.open(p, f, 0o600)) as output:
        output.write(canonical(envelope))


def main():
    import boto3
    from botocore.config import Config
    env = os.environ
    require(env.get('GITHUB_REPOSITORY') == 'IpgoITGO/ipgo-infra' and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_REF') == 'refs/heads/dev' and env.get('GITHUB_RUN_ATTEMPT') == '1'
            and re.fullmatch('[a-f0-9]{40}', env.get('EXPECTED_SHA', ''))
            and env['EXPECTED_SHA'] == env.get('GITHUB_SHA'), 'MANUAL_REVIEWED_DEV_ONLY')
    configuration = json.loads(env['D0_TERRAFORM_JSON'])
    require(configuration.get('enabled') is True and configuration['configuration']['account_id'] == env['AWS_ACCOUNT_ID'],
            'CONFIGURATION_BOUNDARY')
    operation = env.get('OPERATION')
    require(operation in ('preflight', 'plan', 'apply', 'install'), 'OPERATION')
    require(env.get('D0_INSTALL_ENABLED' if operation == 'install' else 'D0_INFRA_ENABLED') == 'true', 'DISABLED')
    if operation in ('apply', 'install'):
        require(re.fullmatch('[a-f0-9]{64}', env.get('EXPECTED_IAM_SNAPSHOT_SHA256', '')), 'REVIEWED_IAM_REQUIRED')
    sdk = Config(retries={'total_max_attempts': 1}, connect_timeout=5, read_timeout=20)
    snapshot = collect(boto3.client('sts', region_name='ap-northeast-2', config=sdk),
                       boto3.client('iam', region_name='ap-northeast-2', config=sdk),
                       configuration['configuration'], env['AWS_APPLY_ROLE_ARN'], env['GITHUB_SHA'], digest(configuration),
                       run_id=env['GITHUB_RUN_ID'], operation=operation, install=operation == 'install',
                       include_runner=configuration.get('runtime_enabled') is True or env.get('REVOKE_RUNTIME') == 'true')
    if snapshot['success']:
        try:
            validate_snapshot(snapshot, env, configuration)
        except PreflightError as error:
            snapshot['success'] = False
            snapshot['failure'] = {'api': 'local:Validation', 'target': 'snapshot', 'code': str(error)}
    persist(snapshot, env['RUNNER_TEMP'])
    summary = {'success': snapshot['success'], 'iamSnapshotSha256': snapshot.get('iamSnapshotSha256')}
    if not snapshot['success']:
        summary['failure'] = snapshot['failure']
    print(json.dumps(summary, sort_keys=True))
    require(snapshot['success'], 'IAM_PREFLIGHT_FAILED')


if __name__ == '__main__':
    try:
        os.umask(0o077)
        main()
    except Exception:
        print('IAM 사전 조회/스냅샷 실패. backend/apply/install을 진행하지 않습니다.')
        raise SystemExit(1) from None

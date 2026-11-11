"""Reject changes outside the dedicated TEST billing Secret and server read policy."""
import json
import sys

SECRET = 'aws_secretsmanager_secret.server_billing_test'
POLICY = 'module.identity.aws_iam_role_policy.server_secrets[0]'


def validate(plan):
    for resource in plan.get('resource_changes', []):
        change = resource['change']
        actions = change['actions']
        if actions == ['no-op'] or (resource.get('mode') == 'data' and actions == ['read']):
            continue
        address = resource['address']
        before, after = change.get('before') or {}, change.get('after') or {}
        if address == SECRET and actions == ['create']:
            if after.get('name') != '/ipgo/dev/server-billing-test' or after.get('recovery_window_in_days') != 30:
                raise ValueError('Unexpected TEST Secret name or retention')
        elif address == POLICY and actions == ['update']:
            if before.get('role') != 'ipgo-dev-server-execution' or after.get('role') != before.get('role'):
                raise ValueError('Unexpected execution role')
            unknown = change.get('after_unknown') or {}
            if any(before.get(k) != after.get(k) for k in set(before) | set(after) if k != 'policy' and not unknown.get(k)):
                raise ValueError('Unexpected policy resource property')
            if after.get('policy'):
                old, new = json.loads(before['policy']), json.loads(after['policy'])
                old_statements, new_statements = old['Statement'], new['Statement']
                if len(old_statements) != 1 or len(new_statements) != 1:
                    raise ValueError('Unexpected permission statement')
                a, b = old_statements[0], new_statements[0]
                if any(a.get(k) != b.get(k) for k in set(a) | set(b) if k != 'Resource'):
                    raise ValueError('Permission actions or conditions changed')
                old_resources = a['Resource'] if isinstance(a['Resource'], list) else [a['Resource']]
                new_resources = b['Resource'] if isinstance(b['Resource'], list) else [b['Resource']]
                added = set(new_resources) - set(old_resources)
                if set(old_resources) - set(new_resources) or len(added) != 1 or not all(':secret:/ipgo/dev/server-billing-test-' in r for r in added):
                    raise ValueError('Unexpected secret access change')
            elif not unknown.get('policy'):
                raise ValueError('Missing policy')
        else:
            raise ValueError('Plan contains changes outside TEST billing scope')


if __name__ == '__main__':
    try:
        validate(json.load(sys.stdin))
    except (ValueError, KeyError, TypeError):
        raise SystemExit('TEST_BILLING_PLAN_REJECTED') from None
    print('TEST_BILLING_PLAN_SCOPE_ALLOWED')

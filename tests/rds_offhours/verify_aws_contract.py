"""botocore Stubber만 사용. 네트워크/실제 AWS 호출 없이 RunTask API 구조를 검증한다."""
import datetime as dt
import io
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import boto3
from botocore.stub import Stubber

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/rds_offhours'))
from aws_api import AWS
from controller import Ledger


def main():
    region, account = 'ap-northeast-2', '111111111111'
    prefix = f'arn:aws:ecs:{region}:{account}'
    cluster, td, task = prefix+':cluster/test', prefix+':task-definition/audit:1', prefix+':task/test/'+'a'*32
    c = {'region': region, 'name': 'test-rds', 'db_id': 'test-db', 'cluster_arn': cluster,
         'audit_task_arn': td, 'audit_subnets': ['subnet-11111111'],
         'audit_security_groups': ['sg-11111111'], 'audit_image': 'test@sha256:'+'b'*64}
    clients = {s: boto3.client(s, region_name=region, aws_access_key_id='testing', aws_secret_access_key='testing')
               for s in ('ecs', 'rds', 'dynamodb')}
    api = AWS(c, lambda s: clients[s])
    ecs = clients['ecs']
    with Stubber(ecs) as stub:
        stub.add_response('run_task', {'tasks': [{'taskArn': task}], 'failures': []}, {
            'cluster': cluster, 'taskDefinition': td, 'launchType': 'FARGATE', 'count': 1,
            'clientToken': 'a'*64, 'startedBy': 'ipgo-rds-audit', 'group': 'ipgo-rds-audit',
            'tags': [{'key': 'Controller', 'value': 'test-rds'}],
            'networkConfiguration': {'awsvpcConfiguration': {'subnets': c['audit_subnets'],
                'securityGroups': c['audit_security_groups'], 'assignPublicIp': 'DISABLED'}},
            'overrides': {'containerOverrides': [{'name': 'audit', 'environment': [{'name': 'AUDIT_KEY', 'value': 'a'*64}]}]}})
        assert api.launch_audit('a'*64) == task
        stub.assert_no_pending_responses()
    with Stubber(clients['rds']) as stub:
        stub.add_response('start_db_instance', {}, {'DBInstanceIdentifier': 'test-db'})
        stub.add_response('stop_db_instance', {}, {'DBInstanceIdentifier': 'test-db'})
        api.start()
        api.stop()
        stub.assert_no_pending_responses()
    ledger = Ledger(SimpleNamespace(name='test-ledger'), clients['dynamodb'])
    transaction = {'TransactItems': [
        {'ConditionCheck': {'TableName': 'test-ledger', 'Key': {'id': {'S': 'STOP_BLOCKED'}},
                            'ConditionExpression': 'attribute_not_exists(id)'}},
        {'Put': {'TableName': 'test-ledger', 'Item': {'id': {'S': 'STOP#2026-11-10'}, 'execution': {'S': 'key'}},
                 'ConditionExpression': 'attribute_not_exists(id)'}}]}
    with Stubber(clients['dynamodb']) as stub:
        stub.add_response('transact_write_items', {}, transaction)
        assert ledger.claim_stop('2026-11-10', 'key')
        stub.add_client_error('transact_write_items', service_error_code='TransactionCanceledException', expected_params=transaction)
        assert not ledger.claim_stop('2026-11-10', 'key')
        stub.assert_no_pending_responses()
    print(json.dumps({'source': 'BOTOCORE_STUBBER', 'passed': ['RunTask_shape_and_fixed_overrides',
                      'StartStop_single_target', 'atomic_stop_circuit_and_daily_claim'], 'actual_aws_calls': 0}))


if __name__ == '__main__':
    main()

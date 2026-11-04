"""workflow 자체 중단/timeout도 다음 중지를 차단한다. start 경로는 보존한다."""
import json
import os

from controller import Ledger


def guard(event, config, ledger):
    detail = event.get('detail', {})
    if (event.get('source') != 'aws.states'
        or event.get('detail-type') != 'Step Functions Execution Status Change'
        or detail.get('stateMachineArn') != config['state_machine_arn']
        or detail.get('status') not in ('FAILED', 'TIMED_OUT', 'ABORTED')):
        return {'status': 'IGNORED'}
    ledger.block_stops(detail['executionArn'])
    return {'status': 'STOP_BLOCKED'}


def handler(event, context):
    import boto3
    from botocore.config import Config
    config = json.loads(os.environ['CONFIG'])
    table = boto3.resource('dynamodb', config=Config(retries={'total_max_attempts': 1})).Table(config['ledger_table'])
    return guard(event, config, Ledger(table))

"""Scheduler 입력은 시간/슬롯만 받는다. 대상·증거·설정 override는 받지 않는다."""
import datetime as dt
import json
import os

from policy import identity


def dispatch(event, config, states, now):
    if config.get('apply_approved') is not True:
        return {'status': 'DISABLED'}
    if set(event) != {'slot', 'scheduled_at'}:
        raise ValueError('unexpected_input')
    key = identity(config, event['slot'], event['scheduled_at'], now)
    payload = json.dumps({'key': key, **event}, sort_keys=True, separators=(',', ':'))
    try:
        result = states.start_execution(stateMachineArn=config['state_machine_arn'],
                                        name=key, input=payload)
        return {'status': 'ACCEPTED', 'executionArn': result['executionArn']}
    except states.exceptions.ExecutionAlreadyExists:
        return {'status': 'DUPLICATE'}


def handler(event, context):
    import boto3
    from botocore.config import Config
    config = json.loads(os.environ['CONFIG'])
    return dispatch(event, config, boto3.client('stepfunctions',
                    config=Config(retries={'total_max_attempts': 1})),
                    dt.datetime.now(dt.timezone.utc))

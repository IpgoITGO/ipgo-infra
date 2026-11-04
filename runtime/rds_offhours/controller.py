"""Standard workflow의 한 번의 tick. 상태 원장은 DynamoDB를 정본으로 쓴다."""
import datetime as dt
import json
import os

from policy import KST, deadline, fresh, identity, stop_blockers, timestamp


def result(status, key, reason=None):
    return {'status': status, 'key': key, 'reason': reason}


def tick(event, config, api, ledger, now, owner):
    if config.get('apply_approved') is not True:
        return result('DISABLED', event.get('key'))
    if set(event) != {'key', 'slot', 'scheduled_at'}:
        raise ValueError('unexpected_input')
    key, slot = event['key'], event['slot']
    record = ledger.load(key)
    if not record:
        if key != identity(config, slot, event['scheduled_at'], now):
            raise ValueError('execution_identity_mismatch')
        record = {'key': key, 'slot': slot, 'scheduled_at': event['scheduled_at'], 'phase': 'INIT'}
    if record['slot'] != slot or record['scheduled_at'] != event['scheduled_at']:
        raise ValueError('execution_binding_mismatch')
    if record.get('status') in ('COMPLETE', 'SKIPPED', 'FAILED'):
        return result(record['status'], key, record.get('reason'))
    if not ledger.acquire(key, owner, now):
        return result('WAIT', key, 'lease_busy')
    # 락 획득 전에 읽은 원장은 다른 invocation의 checkpoint보다 오래될 수 있다.
    current = ledger.load(key)
    if current:
        record = current
        if record.get('status') in ('COMPLETE', 'SKIPPED', 'FAILED'):
            ledger.save(record, owner)
            return result(record['status'], key, record.get('reason'))
    try:
        outcome = advance(record, config, api, ledger, now)
    except Exception as error:
        # AWS/DB 원문 오류에는 식별자나 인증정보가 있을 수 있다.
        outcome = ('FAILED', type(error).__name__)
        ledger.block_stops(key)
    status, reason = finalize_audit(record, outcome, api, ledger, now)
    if status != 'WAIT':
        record.update(status=status, reason=reason)
        if status == 'FAILED':
            ledger.block_stops(key)
    ledger.save(record, owner)
    return result(status, key, reason)


def finalize_audit(run, outcome, api, ledger, now):
    """중도 skip/fail도 자기 감사의 실제 종료를 확인한 뒤 마감한다."""
    if outcome[0] == 'WAIT' or not run.get('task_arn') or run.get('audit_closed_at'):
        return outcome
    if 'pending_status' not in run:
        run.update(pending_status=outcome[0], pending_reason=outcome[1],
                   cleanup_started_at=now.isoformat())
    if not run.get('cleanup_intent'):
        run['cleanup_intent'] = True
        ledger.checkpoint(run)
        try:
            api.cleanup_audit(run['task_arn'], run['key'])
        except Exception as error:
            run['cleanup_request_error'] = type(error).__name__
    try:
        if api.audit_stopped(run['task_arn'], run['key']):
            run['cleanup_verified'] = True
            return run['pending_status'], run['pending_reason']
    except Exception as error:
        run['cleanup_read_error'] = type(error).__name__
    if (now - timestamp(run['cleanup_started_at'])).total_seconds() >= 180:
        run['cleanup_unverified'] = True
        ledger.block_stops(run['key'])
        return 'FAILED', 'audit_cleanup_unverified'
    return 'WAIT', 'audit_cleanup_pending'


def advance(run, config, api, ledger, now):
    if 'pending_status' in run:
        return run['pending_status'], run['pending_reason']
    slot, key = run['slot'], run['key']
    db = api.database()
    if db['DBInstanceArn'] != config['db_arn'] or db['DBInstanceIdentifier'] != config['db_id']:
        raise ValueError('wrong_database')
    state = db['DBInstanceStatus']
    end = deadline(slot, run['scheduled_at'])
    if now >= end:
        # 이미 접수한 Stop이 늦어지면 실패와 원장을 보존한다. 재접수하지 않는다.
        return ('FAILED' if slot != 'stop04' or run.get('stop_intent') else 'SKIPPED', 'deadline')
    if slot != 'stop04':
        if slot == 'recovery':
            ledger.block_stops(key)
        if (slot == 'business07' and state != 'available'
            and now >= timestamp(run['scheduled_at']) + dt.timedelta(minutes=90)
            and not run.get('early_warning_intent')):
            run['early_warning_intent'] = True
            ledger.checkpoint(run)
            api.warn(key, 'business_database_not_available_at_0830')
        if state == 'stopped' and not run.get('start_intent'):
            # 접수 전 durable intent. API 응답 유실 때 같은 요청을 재전송하지 않는다.
            run['start_intent'] = True
            ledger.checkpoint(run)
            api.start()
            return 'WAIT', 'start_requested'
        if state != 'available':
            return 'WAIT', 'read_only_state_poll'
        if slot not in ('business07', 'recovery'):
            return 'COMPLETE', 'available_sql_not_tested'
        if slot == 'business07' and now.astimezone(KST).hour < 9:
            return 'WAIT', 'waiting_for_09_audit'
        audit = audit_step(run, api, ledger, now)
        if audit is None:
            return 'WAIT', 'audit_pending'
        return 'COMPLETE', 'available_and_readonly_audit_passed'

    if ledger.stops_blocked():
        return 'SKIPPED', 'stop_circuit_open'
    if run.get('stop_intent'):
        if state == 'stopped':
            return 'COMPLETE', 'stopped'
        return 'WAIT', 'stop_intent_no_repeat'
    if state != 'available':
        return 'SKIPPED', 'database_not_available'
    # 실제 가동 복구와 다른 start 슬롯은 stop_enabled/circuit에 의존하지 않는다.
    if config.get('stop_enabled') is not True:
        return 'SKIPPED', 'stop_disabled'
    proof = api.proof(db, now, run.get('task_arn'), key)
    # 감사를 실행하기 전에도 승인·기간·관측·백업·writer·LLM 등 먼저 검사한다.
    pre = dict(proof, audit_verified=True, queues_zero_twice=True,
               connections_zero_after_audit=True)
    failures = stop_blockers(config, pre, now)
    if failures:
        return 'SKIPPED', ','.join(failures)
    audit = audit_step(run, api, ledger, now)
    if audit is None:
        return 'WAIT', 'audit_pending'
    proof['audit_verified'] = True
    queues = api.empty_queues()
    if not queues:
        return 'SKIPPED', 'nonempty_or_unknown_queue'
    previous = run.get('queue_sample_at')
    if previous is None:
        run['queue_sample_at'] = now.isoformat()
        return 'WAIT', 'first_empty_queue_sample'
    if (now - timestamp(previous)).total_seconds() < 60:
        return 'WAIT', 'second_queue_sample_not_due'
    proof['queues_zero_twice'] = True
    proof['connections_zero_after_audit'] = api.connections_zero(run['audit_closed_at'], now)
    final_now = api.now()
    failures = stop_blockers(config, proof, final_now)
    if not fresh(audit['observed_at'], final_now, 300):
        failures.append('audit_stale')
    if failures:
        return 'SKIPPED', ','.join(failures)
    # 중지 직전 시간과 새 전제/설정/예약을 다시 읽은 proof가 유효해야 한다.
    if not ledger.claim_stop(final_now.astimezone(KST).date().isoformat(), key):
        return 'SKIPPED', 'daily_stop_already_claimed'
    run['stop_intent'] = True
    ledger.checkpoint(run)
    api.stop()
    return 'WAIT', 'stop_requested'


def audit_step(run, api, ledger, now):
    if 'audit' in run:
        api.verify_audit(run['audit'], run['key'], now)
        return run['audit']
    if 'task_arn' not in run:
        # 감사 budget도 intent 전에 차감. 결과 불명은 당일 추가 감사로 숨기지 않는다.
        if run.get('audit_intent') or not ledger.reserve_audit(now.astimezone(KST).date().isoformat()):
            raise ValueError('audit_budget_or_ambiguous_launch')
        run['audit_intent'] = True
        run['audit_started_at'] = now.isoformat()
        ledger.checkpoint(run)
        run['task_arn'] = api.launch_audit(run['key'])
        ledger.checkpoint(run)
        return None
    if (now - timestamp(run['audit_started_at'])).total_seconds() >= 120:
        raise ValueError('audit_timeout')
    audit = api.audit_result(run['task_arn'], run['key'], now)
    if audit is not None:
        run['audit'] = audit
        run['audit_closed_at'] = now.isoformat()
    return audit


class Ledger:
    def __init__(self, table, transaction_client=None):
        self.table = table
        self.transaction_client = transaction_client
        self.owner = None

    def load(self, key):
        item = self.table.get_item(Key={'id': key}, ConsistentRead=True).get('Item', {})
        return json.loads(item['payload']) if 'payload' in item else None

    def acquire(self, key, owner, now):
        try:
            self.table.update_item(Key={'id': key}, UpdateExpression='SET owner_id=:o, lock_until=:u',
                ConditionExpression='attribute_not_exists(lock_until) OR lock_until < :n',
                ExpressionAttributeValues={':o': owner, ':u': int(now.timestamp()) + 90,
                                           ':n': int(now.timestamp())})
            self.owner = owner
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def checkpoint(self, run):
        self.table.update_item(Key={'id': run['key']},
            UpdateExpression='SET payload=:p', ConditionExpression='owner_id=:o',
            ExpressionAttributeValues={':p': json.dumps(run, sort_keys=True), ':o': self.owner})

    def save(self, run, owner):
        self.table.update_item(Key={'id': run['key']},
            UpdateExpression='SET payload=:p REMOVE owner_id, lock_until',
            ConditionExpression='owner_id=:o',
            ExpressionAttributeValues={':p': json.dumps(run, sort_keys=True), ':o': owner})

    def block_stops(self, key):
        # 최초 오류만 보존. 후속 성공으로 circuit을 자동 해제하지 않는다.
        try:
            self.table.put_item(Item={'id': 'STOP_BLOCKED', 'first_failure': key},
                                ConditionExpression='attribute_not_exists(id)')
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            pass

    def stops_blocked(self):
        return 'Item' in self.table.get_item(Key={'id': 'STOP_BLOCKED'}, ConsistentRead=True)

    def reserve_audit(self, day):
        try:
            self.table.update_item(Key={'id': 'AUDIT#' + day},
                UpdateExpression='ADD attempts :one',
                ConditionExpression='attribute_not_exists(attempts) OR attempts < :two',
                ExpressionAttributeValues={':one': 1, ':two': 2})
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def claim_stop(self, day, key):
        if self.transaction_client is None:
            raise ValueError('atomic_stop_claim_client_missing')
        try:
            self.transaction_client.transact_write_items(TransactItems=[
                {'ConditionCheck': {'TableName': self.table.name, 'Key': {'id': {'S': 'STOP_BLOCKED'}},
                                    'ConditionExpression': 'attribute_not_exists(id)'}},
                {'Put': {'TableName': self.table.name,
                         'Item': {'id': {'S': 'STOP#' + day}, 'execution': {'S': key}},
                         'ConditionExpression': 'attribute_not_exists(id)'}}])
            return True
        except self.transaction_client.exceptions.TransactionCanceledException:
            return False


def handler(event, context):
    import boto3
    from botocore.config import Config
    from aws_api import AWS
    config = json.loads(os.environ['CONFIG'])
    session = boto3.session.Session(region_name=config['region'])
    client_config = Config(retries={'total_max_attempts': 1}, connect_timeout=3, read_timeout=8)
    api = AWS(config, lambda service: session.client(service, config=client_config))
    ledger = Ledger(session.resource('dynamodb', config=client_config).Table(config['ledger_table']),
                    session.client('dynamodb', config=client_config))
    output = tick(event, config, api, ledger, dt.datetime.now(dt.timezone.utc), context.aws_request_id)
    print(json.dumps(output))  # 상태/해시 ID/정형 사유만 기록
    return output

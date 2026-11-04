import copy
import datetime as dt
import io
import json
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/rds_offhours'))
from aws_api import AWS
from aws_api import EXPECTED_DB_CONFIGURATION
from controller import tick
from dispatcher import dispatch
from failure_guard import guard
from policy import KST, digest, identity, stop_blockers

NOW = dt.datetime(2026, 11, 10, 4, tzinfo=KST)


def config():
    return {'apply_approved': True, 'stop_enabled': True, 'db_id': 'test', 'db_arn': 'db:test',
            'revision': 'test1', 'stop_not_before': '2026-11-10T04:00:00+09:00',
            'stop_disabled_from': '2026-11-30T00:00:00+09:00', 'state_machine_arn': 'sm:test'}


def proof(now=NOW):
    keys = ('stability_complete night_test_passed night_cleanup_verified '
            'db_users_and_internal_jobs_confirmed pilot_passed app_recovery_passed '
            'source_matches registry_matches scheduled_start_path_verified backup_completed_today '
            'maintenance_not_pending rds_configuration_matches all_writer_hosts_stopped '
            'no_standalone_writer queues_zero_twice connections_zero_after_audit audit_verified '
            'llm_disabled no_conflicting_lease').split()
    return dict.fromkeys(keys, True) | {'stability_seconds': 86400, 'observed_at': now.isoformat()}


class MemoryLedger:
    def __init__(self):
        self.rows, self.blocked, self.budget, self.stops = {}, False, 0, set()
        self.busy = False

    def load(self, key):
        return copy.deepcopy(self.rows.get(key))

    def acquire(self, *args):
        return not self.busy

    def checkpoint(self, run):
        self.rows[run['key']] = copy.deepcopy(run)

    def save(self, run, owner):
        self.checkpoint(run)

    def block_stops(self, key):
        self.blocked = True

    def stops_blocked(self):
        return self.blocked

    def reserve_audit(self, day):
        self.budget += 1
        return self.budget <= 2

    def claim_stop(self, day, key):
        if day in self.stops:
            return False
        self.stops.add(day)
        return True


class FakeAWS:
    def __init__(self):
        self.state, self.starts, self.stops, self.audits, self.cleanups = 'available', 0, 0, 0, 0
        self.p, self.queue_empty, self.zero_connections = proof(), True, True
        self.audit_pending, self.error = False, False

    def database(self):
        return {'DBInstanceArn': 'db:test', 'DBInstanceIdentifier': 'test', 'DBInstanceStatus': self.state}

    def start(self):
        self.starts += 1
        if self.error:
            raise TimeoutError('SENSITIVE_MUST_NOT_BE_RETURNED')

    def stop(self):
        self.stops += 1
        if self.error:
            raise TimeoutError('SENSITIVE_MUST_NOT_BE_RETURNED')

    def proof(self, db, now, *args):
        self.current_time = now
        return dict(self.p, observed_at=now.isoformat())

    def now(self):
        return getattr(self, 'delayed_time', self.current_time)

    def launch_audit(self, key):
        self.audits += 1
        return 'task:test'

    def audit_result(self, arn, key, now):
        if self.audit_pending:
            return None
        return {'observed_at': now.isoformat(), 'key': key}

    def verify_audit(self, audit, key, now):
        if audit['key'] != key:
            raise ValueError('invalid_audit')

    def cleanup_audit(self, arn, key):
        self.cleanups += bool(arn)

    def audit_stopped(self, arn, key):
        return getattr(self, 'cleanup_complete', True)

    def empty_queues(self):
        return self.queue_empty

    def connections_zero(self, *args):
        return self.zero_connections


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.c, self.api, self.ledger = config(), FakeAWS(), MemoryLedger()
        self.event = self.event_at('stop04', NOW)

    def event_at(self, slot, when):
        return {'key': identity(self.c, slot, when.isoformat(), when),
                'slot': slot, 'scheduled_at': when.isoformat()}

    def run_tick(self, seconds=0, event=None):
        return tick(event or self.event, self.c, self.api, self.ledger,
                    NOW + dt.timedelta(seconds=seconds), 'owner')

    def prepare_stop(self):
        self.assertEqual(self.run_tick()['status'], 'WAIT')
        self.assertEqual(self.run_tick(60)['reason'], 'first_empty_queue_sample')

    def test_full_stop_and_no_duplicate(self):
        self.prepare_stop()
        self.assertEqual(self.run_tick(120)['reason'], 'stop_requested')
        self.run_tick(180)
        self.assertEqual(self.api.stops, 1)
        self.api.state = 'stopped'
        self.assertEqual(self.run_tick(240)['status'], 'COMPLETE')
        self.run_tick(300)
        self.assertEqual(self.api.stops, 1)

    def test_stop_unknown_acceptance_preserves_first_failure(self):
        self.prepare_stop()
        self.api.error = True
        first = self.run_tick(120)
        self.assertEqual(first['reason'], 'TimeoutError')
        self.assertNotIn('SENSITIVE', json.dumps(first))
        self.api.state = 'stopped'
        self.assertEqual(self.run_tick(180), first)
        self.assertEqual(self.api.stops, 1)
        self.assertTrue(self.ledger.blocked)

    def test_start_survives_stop_circuit_and_stop_disabled(self):
        self.ledger.blocked = True
        self.c['stop_enabled'] = False
        self.api.state = 'stopped'
        at = NOW.replace(hour=7)
        event = self.event_at('business07', at)
        out = tick(event, self.c, self.api, self.ledger, at, 'owner')
        self.assertEqual(out['reason'], 'start_requested')
        self.assertEqual(self.api.starts, 1)
        tick(event, self.c, self.api, self.ledger, at + dt.timedelta(minutes=1), 'owner')
        self.assertEqual(self.api.starts, 1)

    def test_transition_never_repeats_start(self):
        for state in ('starting', 'stopping', 'backing-up', 'modifying'):
            self.api.state = state
            at = NOW.replace(hour=7)
            event = self.event_at('business07', at)
            self.assertEqual(tick(event, self.c, self.api, self.ledger, at, 'owner')['status'], 'WAIT')
        self.assertEqual(self.api.starts, 0)

    def test_disabled_is_zero_calls(self):
        self.c['apply_approved'] = False
        self.assertEqual(tick({}, self.c, Mock(), Mock(), NOW, 'owner')['status'], 'DISABLED')

    def test_lease_busy(self):
        self.ledger.busy = True
        self.assertEqual(self.run_tick()['reason'], 'lease_busy')
        self.assertEqual(self.api.audits, 0)

    def test_lease_reloads_latest_intent(self):
        acquire = self.ledger.acquire
        def concurrent_checkpoint(*args):
            self.ledger.rows[self.event['key']] = dict(self.event, phase='INIT', start_intent=True,
                stop_intent=True)
            return acquire(*args)
        self.ledger.acquire = concurrent_checkpoint
        self.assertEqual(self.run_tick()['reason'], 'stop_intent_no_repeat')
        self.assertEqual(self.api.stops, 0)
        self.assertEqual(self.api.audits, 0)

    def test_backup_available_is_not_sql_success(self):
        at = NOW.replace(hour=0)
        event = self.event_at('backup00', at)
        out = tick(event, self.c, self.api, self.ledger, at, 'owner')
        self.assertEqual(out['reason'], 'available_sql_not_tested')
        self.assertEqual(self.api.audits, 0)

    def test_business_waits_until_nine_then_audits(self):
        at = NOW.replace(hour=7)
        event = self.event_at('business07', at)
        self.assertEqual(tick(event, self.c, self.api, self.ledger, at, 'owner')['reason'], 'waiting_for_09_audit')
        self.assertEqual(tick(event, self.c, self.api, self.ledger, at.replace(hour=9), 'owner')['reason'], 'audit_pending')
        self.assertEqual(tick(event, self.c, self.api, self.ledger, at.replace(hour=9, minute=1), 'owner')['reason'],
                         'available_and_readonly_audit_passed')

    def test_business_failure_leaves_db_available_and_blocks_stops(self):
        at = NOW.replace(hour=7)
        event = self.event_at('business07', at)
        tick(event, self.c, self.api, self.ledger, at, 'owner')
        out = tick(event, self.c, self.api, self.ledger, at.replace(hour=9, minute=30), 'owner')
        self.assertEqual(out['status'], 'FAILED')
        self.assertEqual(self.api.state, 'available')
        self.assertTrue(self.ledger.blocked)

    def test_0830_early_warning_is_once_and_polling_continues(self):
        self.api.warn = Mock()
        self.api.state = 'starting'
        at = NOW.replace(hour=7)
        event = self.event_at('business07', at)
        tick(event, self.c, self.api, self.ledger, at, 'owner')
        for minute in (30, 31):
            out = tick(event, self.c, self.api, self.ledger, at.replace(hour=8, minute=minute), 'owner')
            self.assertEqual(out['status'], 'WAIT')
        self.api.warn.assert_called_once()

    def test_recovery_immediate_start_then_sql_without_new_schedule(self):
        self.c['stop_enabled'] = False
        self.api.state = 'stopped'
        event = self.event_at('recovery', NOW)
        self.assertEqual(self.run_tick(event=event)['reason'], 'start_requested')
        self.assertTrue(self.ledger.blocked)
        self.api.state = 'available'
        self.assertEqual(self.run_tick(60, event)['reason'], 'audit_pending')
        self.assertEqual(self.run_tick(120, event)['reason'], 'available_and_readonly_audit_passed')
        self.assertEqual(self.api.starts, 1)

    def test_each_missing_proof_blocks_before_audit(self):
        for key, value in proof().items():
            if value is True:
                self.api.p = proof()
                del self.api.p[key]
                self.ledger = MemoryLedger()
                if key in ('audit_verified', 'queues_zero_twice', 'connections_zero_after_audit'):
                    continue  # 이 세 값은 실제 호출에서 수집한다.
                with self.subTest(key=key):
                    self.assertEqual(self.run_tick()['status'], 'SKIPPED')
        self.assertEqual(self.api.audits, 0)

    def test_audit_timeout_cleanup_and_block(self):
        self.api.audit_pending = True
        self.run_tick()
        self.run_tick(60)
        self.assertEqual(self.run_tick(120)['status'], 'FAILED')
        self.assertTrue(self.ledger.blocked)
        self.assertGreater(self.api.cleanups, 0)

    def test_gate_change_during_audit_waits_for_cleanup_once(self):
        self.api.cleanup_complete = False
        self.run_tick()
        self.api.p['maintenance_not_pending'] = False
        self.assertEqual(self.run_tick(60)['reason'], 'audit_cleanup_pending')
        self.assertEqual(self.run_tick(120)['reason'], 'audit_cleanup_pending')
        self.assertEqual(self.api.cleanups, 1)
        self.api.cleanup_complete = True
        out = self.run_tick(180)
        self.assertEqual(out['status'], 'SKIPPED')
        self.assertIn('maintenance_not_pending', out['reason'])
        self.assertTrue(self.ledger.rows[self.event['key']]['cleanup_verified'])

    def test_cleanup_timeout_preserves_original_failure(self):
        self.api.cleanup_complete = False
        self.api.audit_pending = True
        self.run_tick()
        self.run_tick(120)
        self.assertEqual(self.run_tick(300)['reason'], 'audit_cleanup_unverified')
        run = self.ledger.rows[self.event['key']]
        self.assertEqual(run['pending_reason'], 'ValueError')
        self.assertTrue(run['cleanup_unverified'])
        self.assertTrue(self.ledger.blocked)

    def test_budget_does_not_retry_launch(self):
        self.ledger.budget = 2
        self.assertEqual(self.run_tick()['status'], 'FAILED')
        self.assertEqual(self.api.audits, 0)

    def test_nonempty_queue_skips(self):
        self.run_tick()
        self.api.queue_empty = False
        self.assertEqual(self.run_tick(60)['status'], 'SKIPPED')
        self.assertEqual(self.api.stops, 0)

    def test_missing_connection_metric_skips(self):
        self.prepare_stop()
        self.api.zero_connections = False
        self.assertEqual(self.run_tick(120)['status'], 'SKIPPED')
        self.assertEqual(self.api.stops, 0)

    def test_duplicate_stop_claim_across_revision(self):
        self.prepare_stop()
        self.ledger.stops.add('2026-11-10')
        self.assertEqual(self.run_tick(120)['reason'], 'daily_stop_already_claimed')
        self.assertEqual(self.api.stops, 0)

    def test_deadline_no_new_stop(self):
        self.run_tick()
        self.assertEqual(self.run_tick(1800)['status'], 'SKIPPED')
        self.assertEqual(self.api.stops, 0)

    def test_proof_calls_crossing_stop_deadline_skip_write(self):
        self.prepare_stop()
        self.api.delayed_time = NOW.replace(minute=30)
        self.assertEqual(self.run_tick(120)['status'], 'SKIPPED')
        self.assertEqual(self.api.stops, 0)

    def test_wrong_target_fails(self):
        self.c['db_arn'] = 'different'
        self.event = self.event_at('stop04', NOW)
        self.assertEqual(self.run_tick()['reason'], 'ValueError')
        self.assertEqual(self.api.stops, 0)

    def test_future_and_late_event_rejected(self):
        for seconds in (-1, 91):
            with self.assertRaises(ValueError):
                identity(self.c, 'stop04', NOW.isoformat(), NOW + dt.timedelta(seconds=seconds))

    def test_slot_separates_same_day_starts(self):
        a = identity(self.c, 'backup00', NOW.replace(hour=0).isoformat(), NOW.replace(hour=0))
        b = identity(self.c, 'business07', NOW.replace(hour=7).isoformat(), NOW.replace(hour=7))
        self.assertNotEqual(a, b)

    def test_stop_period_and_proof_freshness(self):
        for when in (NOW.replace(hour=5), NOW.replace(day=30), NOW.replace(day=9)):
            self.assertTrue(stop_blockers(self.c, proof(when), when))
        self.assertTrue(stop_blockers(self.c, proof(NOW-dt.timedelta(seconds=181)), NOW))

    def test_nan_false_string_and_boolean_duration_rejected(self):
        for duration in (float('nan'), float('inf'), True, '86400', 86399):
            self.assertIn('insufficient_stability', stop_blockers(self.c, proof() | {'stability_seconds': duration}, NOW))
        self.assertIn('night_test_passed', stop_blockers(self.c, proof() | {'night_test_passed': 'true'}, NOW))

    def test_dispatch_input_and_duplicate(self):
        states = Mock()
        states.exceptions.ExecutionAlreadyExists = type('Already', (Exception,), {})
        states.start_execution.side_effect = states.exceptions.ExecutionAlreadyExists()
        event = {k: self.event[k] for k in ('slot', 'scheduled_at')}
        self.assertEqual(dispatch(event, self.c, states, NOW)['status'], 'DUPLICATE')
        with self.assertRaises(ValueError):
            dispatch(event | {'proof': proof()}, self.c, states, NOW)

    def test_failure_guard_scope(self):
        event = {'source': 'aws.states', 'detail-type': 'Step Functions Execution Status Change',
                 'detail': {'stateMachineArn': 'sm:test', 'status': 'TIMED_OUT', 'executionArn': 'exec:test'}}
        self.assertEqual(guard(event, self.c, self.ledger)['status'], 'STOP_BLOCKED')
        self.assertEqual(guard(event | {'source': 'other'}, self.c, self.ledger)['status'], 'IGNORED')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.c = config() | {'bucket': 'bucket', 'manifest_key': 'manifest', 'manifest_version': 'version',
                             'result_prefix': 'results', 'queue_urls': ['q1', 'q2', 'q3', 'q4']}
        self.clients = {}
        self.api = AWS(self.c, lambda name: self.clients.setdefault(name, Mock()))

    def test_all_queues_all_attributes_required(self):
        sqs = self.api.client('sqs')
        sqs.get_queue_attributes.return_value = {'Attributes': dict.fromkeys([
            'ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible', 'ApproximateNumberOfMessagesDelayed'], '0')}
        self.assertTrue(self.api.empty_queues())
        sqs.get_queue_attributes.return_value = {'Attributes': {'a': '0'}}
        self.assertFalse(self.api.empty_queues())

    def test_metrics_missing_stale_nan_or_nonzero_fail(self):
        cw = self.api.client('cloudwatch')
        for points in ([], [{'Timestamp': NOW, 'Maximum': float('nan')}],
                       [{'Timestamp': NOW-dt.timedelta(minutes=4), 'Maximum': 0}],
                       [{'Timestamp': NOW, 'Maximum': 0}, {'Timestamp': NOW, 'Maximum': 1}]):
            cw.get_metric_statistics.return_value = {'Datapoints': points}
            self.assertFalse(self.api.connections_zero((NOW-dt.timedelta(minutes=5)).isoformat(), NOW))

    def test_manifest_is_version_pinned_and_bounded(self):
        s3 = self.api.client('s3')
        s3.get_object.return_value = {'Body': io.BytesIO(b'{}')}
        self.api.read_json('manifest', 'version')
        s3.get_object.assert_called_once_with(Bucket='bucket', Key='manifest', VersionId='version')
        s3.get_object.return_value = {'Body': io.BytesIO(b' ' * 65537)}
        with self.assertRaises(ValueError):
            self.api.read_json('manifest')

    def test_audit_identity_schema_numeric_and_freshness(self):
        self.api.manifest = lambda now: {'schema_sha256': 'schema', 'reference_sha256': 'ref'}
        valid = {'key': 'key', 'db_arn': self.c['db_arn'], 'observed_at': NOW.isoformat(), 'ok': True,
                 'read_only': True, 'tls_verified': True, 'schema_sha256': 'schema', 'reference_sha256': 'ref',
                 'active_engine_jobs': 0, 'open_business_transactions': 0, 'llm_explanation_violations': 0}
        self.api.verify_audit(valid, 'key', NOW)
        for key, value in [('key', 'foreign'), ('db_arn', 'other'), ('schema_sha256', 'drift'),
                           ('open_business_transactions', False), ('active_engine_jobs', '0'),
                           ('llm_explanation_violations', 1), ('ok', 'true'),
                           ('observed_at', (NOW-dt.timedelta(seconds=301)).isoformat())]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.api.verify_audit(valid | {key: value}, 'key', NOW)

    def test_pagination_all_pages(self):
        rds = self.api.client('rds')
        rds.describe_db_snapshots.side_effect = [{'DBSnapshots': [1], 'Marker': 'two'}, {'DBSnapshots': [2]}]
        self.assertEqual(self.api.pages('rds', 'describe_db_snapshots', 'DBSnapshots'), [1, 2])

    def test_foreign_task_cannot_be_stopped(self):
        self.c['cluster_arn'], self.c['audit_task_arn'] = 'cluster', 'audit:1'
        ecs = self.api.client('ecs')
        ecs.describe_tasks.return_value = {'tasks': [{'taskDefinitionArn': 'foreign'}]}
        with self.assertRaises(ValueError):
            self.api.cleanup_audit('task:other', 'key')
        ecs.stop_task.assert_not_called()

    def test_audit_requires_exit_zero_and_digest(self):
        self.api.owned_task = lambda *a: {'lastStatus': 'STOPPED', 'containers': [{'exitCode': 1}]}
        with self.assertRaises(ValueError):
            self.api.audit_result('task', 'key', NOW)

    def test_live_stop_proof_binds_backup_source_registry_and_hosts(self):
        self.c.update(writer_instance_ids=['host'], cluster_arn='cluster', service_task_arns=['server:5', 'ai:4'],
            service_arns=['arn:aws:ecs:test:111111111111:service/cluster/server', 'arn:aws:ecs:test:111111111111:service/cluster/ai'],
            existing_schedule_arns=['arn:aws:scheduler:test:111111111111:schedule/actual-group/'+x for x in ('start', 'stop')])
        containers = [{'name': 'ai', 'environment': [{'name': 'LLM_ENABLED', 'value': 'false'}]}]
        binding = {'State': 'ENABLED', 'ScheduleExpression': 'cron(test)',
                   'ScheduleExpressionTimezone': 'Asia/Seoul', 'Target': {'Arn': 'fixed'}}
        m = {'prerequisites': proof(), 'db_configuration': EXPECTED_DB_CONFIGURATION,
             'service_definitions': {'server': digest(containers), 'ai': digest(containers)},
             'existing_schedules': [{'name': x, 'group': 'actual-group', 'sha256': digest(binding)} for x in ('start', 'stop')]}
        self.api.manifest = lambda now: m
        rds, ec2, ecs, scheduler, states = [self.api.client(s) for s in ('rds', 'ec2', 'ecs', 'scheduler', 'stepfunctions')]
        rds.describe_pending_maintenance_actions.return_value = {'PendingMaintenanceActions': []}
        rds.describe_db_snapshots.return_value = {'DBSnapshots': [{'Status': 'available', 'SnapshotCreateTime': NOW.replace(hour=3)}]}
        ec2.describe_instances.return_value = {'Reservations': [{'Instances': [{'InstanceId': 'host', 'State': {'Name': 'stopped'}}]}]}
        ecs.list_tasks.return_value = {'taskArns': []}
        ecs.describe_services.side_effect = lambda **kw: {'services': [{'taskDefinition': 'ai:4' if kw['services'] == ['ai'] else 'server:5'}]}
        ecs.describe_task_definition.return_value = {'taskDefinition': {'containerDefinitions': containers}}
        scheduler.get_schedule.return_value = binding
        states.list_executions.side_effect = lambda **kw: {'executions': [{'executionArn': 'current', 'name': 'current-key'}] if kw['statusFilter'] == 'RUNNING' else []}
        db = EXPECTED_DB_CONFIGURATION | {'LatestRestorableTime': NOW.replace(hour=3, minute=55)}
        good = self.api.proof(db, NOW, key='current-key')
        self.assertTrue(all(good[k] for k in ('backup_completed_today', 'all_writer_hosts_stopped',
            'source_matches', 'llm_disabled', 'registry_matches', 'no_conflicting_lease', 'no_standalone_writer')))
        self.assertEqual(scheduler.get_schedule.call_args.kwargs['GroupName'], 'actual-group')
        partial = dict(m, service_definitions={'ai': m['service_definitions']['ai']})
        self.assertEqual(self.api.sources_match(partial), (False, False))
        duplicate = dict(m, existing_schedules=[m['existing_schedules'][0]]*2)
        self.assertFalse(self.api.schedules_match(duplicate))
        self.assertFalse(self.api.proof(db, NOW, key='foreign-key')['no_conflicting_lease'])
        rds.describe_db_snapshots.return_value = {'DBSnapshots': []}
        self.assertFalse(self.api.proof(db, NOW)['backup_completed_today'])
        states.list_executions.side_effect = lambda **kw: {'executions': [{'executionArn': 'unreviewed'}]}
        self.assertFalse(self.api.proof(db, NOW)['no_conflicting_lease'])


if __name__ == '__main__':
    unittest.main()

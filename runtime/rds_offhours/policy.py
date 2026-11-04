"""중지 조건은 전부 닫힌 상태로 평가한다. AWS 호출은 하지 않는다."""
import datetime as dt
import hashlib
import json
import math
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
SLOTS = {'backup00': (0, 0), 'stop04': (4, 0),
         'business07': (7, 0), 'maintenance22': (22, 0), 'recovery': None}


def timestamp(value):
    n = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if n.tzinfo is None:
        raise ValueError('timezone_required')
    return n


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


def identity(config, slot, scheduled, now):
    if slot not in SLOTS:
        raise ValueError('invalid_slot')
    s = timestamp(scheduled).astimezone(KST)
    if (slot != 'recovery' and (s.hour, s.minute) != SLOTS[slot]) or s.second != 0:
        raise ValueError('invalid_slot_time')
    if slot == 'business07' and s.weekday() >= 5:
        raise ValueError('invalid_business_day')
    if slot == 'maintenance22' and s.weekday() != 5:
        raise ValueError('invalid_maintenance_day')
    if not 0 <= (now - s).total_seconds() <= 90:
        raise ValueError('stale_or_future_delivery')
    return digest([config['db_arn'], s.date().isoformat(), slot, config['revision']])


def fresh(value, now, seconds):
    try:
        return 0 <= (now - timestamp(value)).total_seconds() <= seconds
    except (ValueError, TypeError, AttributeError):
        return False


def stop_blockers(config, proof, now):
    n = now.astimezone(KST)
    failures = []
    if config.get('apply_approved') is not True or config.get('stop_enabled') is not True:
        failures.append('not_approved_or_disabled')
    if not timestamp(config['stop_not_before']) <= n < timestamp(config['stop_disabled_from']):
        failures.append('outside_activation_period')
    if n.hour != 4 or n.minute >= 30:
        failures.append('outside_stop_window')
    required = ('stability_complete', 'night_test_passed', 'night_cleanup_verified',
                'db_users_and_internal_jobs_confirmed', 'pilot_passed',
                'app_recovery_passed', 'source_matches', 'registry_matches',
                'scheduled_start_path_verified', 'backup_completed_today',
                'maintenance_not_pending', 'rds_configuration_matches',
                'all_writer_hosts_stopped', 'no_standalone_writer',
                'queues_zero_twice', 'connections_zero_after_audit',
                'audit_verified', 'llm_disabled', 'no_conflicting_lease')
    failures += [k for k in required if proof.get(k) is not True]
    seconds = proof.get('stability_seconds')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 86400:
        failures.append('insufficient_stability')
    if not fresh(proof.get('observed_at'), now, 180):
        failures.append('stale_evidence')
    return failures


def deadline(slot, scheduled):
    s = timestamp(scheduled).astimezone(KST)
    offsets = {'backup00': 150, 'stop04': 30, 'business07': 150, 'maintenance22': 180, 'recovery': 180}
    return s + dt.timedelta(minutes=offsets[slot])

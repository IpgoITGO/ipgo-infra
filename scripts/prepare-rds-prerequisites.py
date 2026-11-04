"""기존 NAS 결과를 읽어 고정 증거 요약을 만든다. 업로드/등록/활성화 기능은 없다.

완료 원문을 함께 보존하고 digest로 묶는다. 이 요약 하나만으로 적용을 승인하지 않는다.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def read(path, origins):
    raw = path.read_bytes()
    origins[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def summarize(stability_path, night_folder):
    origins = {}
    stability = read(stability_path, origins)
    seconds = stability.get('credited_seconds')
    stable = (stability.get('status') == 'complete' and stability.get('llm_enabled') is False
              and stability.get('issues') == [] and type(seconds) in (int, float)
              and math.isfinite(seconds) and seconds >= 86400)
    phases = {}
    for phase in ('hold', 'resume'):
        state = read(night_folder/phase/'state.json', origins)
        phases[phase] = state.get('status') == 'passed' and state.get('phase') == phase
        if phases[phase]:
            v = read(night_folder/phase/'verification.json', origins)
            phases[phase] = (v.get('status') == 'passed' and v.get('llm_enabled') is False
                and v.get('server_sha') == stability.get('server_sha')
                and v.get('ai_sha') == stability.get('ai_sha')
                and all(v.get(k) is True for k in ('production_preserved', 'existing_data_preserved',
                    'existing_configuration_preserved', 'operating_schedule_preserved')))
            # 원본 runner가 이미 세부 검증을 수행한다. 그 원문 증거도 고정해야 한다.
            if not v.get('evidence_files'):
                phases[phase] = False
            for name in v.get('evidence_files', []):
                path = (night_folder / name).resolve()
                if not path.is_relative_to(night_folder.resolve()):
                    raise ValueError('evidence_outside_night_directory')
                raw = path.read_bytes()
                origins[str(path)] = hashlib.sha256(raw).hexdigest()
    cleanup = False
    path = night_folder/'cleanup-verification.json'
    if path.exists():
        data = read(path, origins)
        cleanup = all(data.get(k) is True for k in ('queues_absent', 'role_absent',
                      'own_tasks_stopped', 'definition_inactive', 'ownership_verified'))
        cleanup &= bool(data.get('evidence_files'))
        for name in data.get('evidence_files', []):
            evidence = (night_folder/name).resolve()
            if not evidence.is_relative_to(night_folder.resolve()):
                raise ValueError('cleanup_evidence_outside_directory')
            origins[str(evidence)] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    return {'schema': 1, 'stability_complete': stable, 'stability_seconds': seconds,
            'night_test_passed': all(phases.values()), 'night_cleanup_verified': cleanup,
            'server_sha': stability.get('server_sha'), 'ai_sha': stability.get('ai_sha'),
            'llm_disabled': stability.get('llm_enabled') is False, 'origins_sha256': origins,
            'apply_approved': False, 'stop_enabled': False,
            'requires_review': ['full_night_verification', 'db_users_and_internal_jobs',
                                'pilot_and_app_recovery', 'native_start_path', 'fresh_registry_and_sources']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stability', type=Path, required=True)
    parser.add_argument('--night-folder', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.stability, args.night_folder), ensure_ascii=False, indent=2))

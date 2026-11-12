"""새 독립 root의 검증을 기존 dev 전체 AWS plan으로 오인하지 않게 분류한다."""
import os
import re
import subprocess
from pathlib import Path

ISOLATED = ('terraform/environments/rds-offhours/', 'terraform/modules/rds-offhours/',
            'terraform/environments/d0-validation/', 'terraform/modules/d0-validation/')
DEV_LOCKFILE = 'terraform/environments/dev/.terraform.lock.hcl'


def needs_legacy_dev(paths, manual=False):
    # 수동 전체 plan과 기존 Terraform 경로는 종전 동작을 유지한다.
    return manual or any(p == '.github/workflows/terraform-apply.yml' or
                         (p.startswith('terraform/') and not p.startswith(ISOLATED)) for p in paths)


def changed_paths(base, head, cwd=None):
    if not all(re.fullmatch(r'[0-9a-f]{40}', sha) for sha in (base, head)):
        raise ValueError('invalid_git_identity')
    # PR base가 먼저 전진해도 다른 PR의 변경을 이 브랜치의 삭제로 오인하지 않는다.
    raw = subprocess.check_output(['git', 'diff', '--merge-base', '--no-renames', '--name-only', '-z', base, head], cwd=cwd)
    return raw.decode('utf-8', errors='surrogateescape').rstrip('\0').split('\0')


def prepare_dependency(source, event, cwd=None):
    """수동 검토한 lockfile만 가져오며 PR의 workflow/script는 실행하지 않는다."""
    if not source:
        return
    if event != 'workflow_dispatch' or not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('dependency_plan_requires_manual_full_sha')
    base = subprocess.check_output(['git', 'rev-parse', 'origin/dev'], cwd=cwd).decode().strip()
    if changed_paths(base, source, cwd) != [DEV_LOCKFILE]:
        raise ValueError('dependency_plan_requires_only_dev_lockfile')
    source_changes = subprocess.check_output(['git', 'diff', '--name-only', base, source, '--', 'terraform/'], cwd=cwd).decode().splitlines()
    if source_changes != [DEV_LOCKFILE]:
        raise ValueError('dependency_plan_requires_current_dev_terraform')
    # 최신 dev와 같은 Terraform 코드에서만 원래 PR의 provider plan으로 해석한다.
    if subprocess.check_output(['git', 'diff', '--name-only', base, 'HEAD', '--', 'terraform/'], cwd=cwd):
        raise ValueError('dependency_plan_requires_dev_terraform_baseline')
    content = subprocess.check_output(['git', 'show', source + ':' + DEV_LOCKFILE], cwd=cwd)
    (Path(cwd or '.') / DEV_LOCKFILE).write_bytes(content)
    print('Reviewed dependency lockfile prepared: ' + source)


def main():
    event = os.environ['SOURCE_EVENT']
    prepare_dependency(os.environ.get('DEPENDENCY_SHA', ''), event)
    manual = event == 'workflow_dispatch'
    paths = []
    if not manual:
        base, head = os.environ['BASE_SHA'], os.environ['HEAD_SHA']
        # 이름 변경도 삭제된 기존 경로까지 포함한다. diff 오류는 실패로 끝내며 skip으로 바꾸지 않는다.
        paths = changed_paths(base, head)
    value = 'true' if needs_legacy_dev(paths, manual) else 'false'
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
        stream.write('legacy_dev=' + value + '\n')
    print('legacy_dev_plan_required=' + value)


if __name__ == '__main__':
    main()

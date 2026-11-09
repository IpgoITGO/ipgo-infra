"""새 독립 root의 검증을 기존 dev 전체 AWS plan으로 오인하지 않게 분류한다."""
import os
import re
import subprocess

ISOLATED = ('terraform/environments/rds-offhours/', 'terraform/modules/rds-offhours/',
            'terraform/environments/d0-validation/', 'terraform/modules/d0-validation/')


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


def main():
    manual = os.environ['SOURCE_EVENT'] == 'workflow_dispatch'
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

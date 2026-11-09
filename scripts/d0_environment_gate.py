"""보호 environment를 OIDC 발급 전에 실제 읽기 확인한다."""
import json
import os
import urllib.request

def require(value, code):
    if not value:
        raise ValueError(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP_REDIRECT')


def validate_environment(environment, branches):
    reviewers = [r for r in environment.get('protection_rules', []) if r.get('type') == 'required_reviewers']
    require(len(reviewers) == 1 and len(reviewers[0].get('reviewers', [])) >= 1, 'ENVIRONMENT_REVIEW_REQUIRED')
    policy = environment.get('deployment_branch_policy') or {}
    require(policy.get('custom_branch_policies') is True and policy.get('protected_branches') is False,
            'ENVIRONMENT_BRANCH_POLICY')
    policies = branches.get('branch_policies', [])
    require(len(policies) == 1 and policies[0].get('name') == 'dev'
            and policies[0].get('type', 'branch') == 'branch', 'ENVIRONMENT_DEV_ONLY')


def inspect_environment(repository, name, token):
    require(repository in ('IpgoITGO/ipgo-server', 'IpgoITGO/ipgo-infra')
            and name in ('d0-validation', 'dev'), 'GITHUB_ENVIRONMENT_TARGET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def read(suffix):
        request = urllib.request.Request(f'https://api.github.com/repos/{repository}/environments/{name}' + suffix,
            headers={'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + token,
                     'X-GitHub-Api-Version': '2022-11-28'})
        with opener.open(request, timeout=15) as response:
            require(response.status == 200, 'ENVIRONMENT_READ')
            return json.loads(response.read(1024 * 1024))
    validate_environment(read(''), read('/deployment-branch-policies'))


if __name__ == '__main__':
    try:
        inspect_environment(os.environ['GITHUB_REPOSITORY'], 'dev', os.environ['GH_TOKEN'])
        print('기존 Infra environment 승인자/dev정책 읽기 확인. 기존 자기승인 정책 유지.')
    except Exception:
        print('전용 environment 보호/읽기 권한 확인 실패. OIDC를 발급하지 않습니다.')
        raise SystemExit(1) from None

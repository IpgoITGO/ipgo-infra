#!/usr/bin/env python3
"""현재 ECS 정의로 메일 주입 후보만 만든다. AWS 호출·Secret 값 취급·배포는 하지 않는다."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re


REGISTER_FIELDS = {
    'family', 'taskRoleArn', 'executionRoleArn', 'networkMode', 'containerDefinitions',
    'volumes', 'placementConstraints', 'requiresCompatibilities', 'cpu', 'memory',
    'pidMode', 'ipcMode', 'proxyConfiguration', 'inferenceAccelerators',
    'ephemeralStorage', 'runtimePlatform', 'enableFaultInjection', 'tags',
}
RESPONSE_FIELDS = {
    'taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'compatibilities',
    'registeredAt', 'registeredBy', 'deregisteredAt',
}
MAIL_ENV = {
    'SPRING_MAIL_HOST': 'smtp.gmail.com', 'SPRING_MAIL_PORT': '587',
    'SPRING_MAIL_PROPERTIES_MAIL_SMTP_AUTH': 'true',
    'SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_ENABLE': 'true',
    'SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_REQUIRED': 'true',
    'SPRING_MAIL_PROPERTIES_MAIL_SMTP_SSL_ENABLE': 'false',
}
MAIL_SECRETS = {'SPRING_MAIL_PASSWORD'}
IDENTITY_ENV = {'SPRING_MAIL_USERNAME', 'IPGO_MAIL_FROM'}


def prepare(document, *, expected_definition, expected_image, secret_arn, mail_config):
    original = document.get('taskDefinition', document)
    if original.get('taskDefinitionArn') != expected_definition:
        raise ValueError('승인 기준 task definition이 다릅니다')
    scope = re.fullmatch(r'arn:aws:ecs:(ap-northeast-2):(\d{12}):task-definition/ipgo-dev-onebox-server:(\d+)', expected_definition)
    if not scope or original.get('family') != 'ipgo-dev-onebox-server':
        raise ValueError('개발 onebox 서버만 지원합니다')
    secret = re.fullmatch(r'arn:aws:secretsmanager:(ap-northeast-2):(\d{12}):secret:([A-Za-z0-9/_+=.@-]+)', secret_arn)
    if not secret or secret.group(1, 2) != scope.group(1, 2):
        raise ValueError('Secret은 같은 계정·서울 리전이어야 하며 전체 리소스 ARN이 필요합니다')
    if not re.fullmatch(r'/ipgo/dev/server-mail-password-[A-Za-z0-9]{6}', secret.group(3)):
        raise ValueError('기존 Infra PR34의 전용 password Secret만 지원합니다')
    if set(mail_config) != IDENTITY_ENV:
        raise ValueError('계정·발신 설정 이름을 확인해 주세요. 비밀번호는 입력하지 않습니다')
    if any(not isinstance(v, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', v) for v in mail_config.values()):
        raise ValueError('계정·발신 주소 형식을 확인해 주세요')
    if mail_config['SPRING_MAIL_USERNAME'] != mail_config['IPGO_MAIL_FROM']:
        raise ValueError('현재 개발 Gmail 계정과 발신 주소는 같아야 합니다')
    if original.get('networkMode') != 'bridge' or original.get('requiresCompatibilities') != ['EC2']:
        raise ValueError('현재 EC2 bridge 구성과 다릅니다')
    unknown = set(original) - REGISTER_FIELDS - RESPONSE_FIELDS
    if unknown:
        raise ValueError('지원하지 않는 task definition 필드가 있습니다')
    if not original.get('executionRoleArn'):
        raise ValueError('ECS execution role이 필요합니다')
    candidate = {k: copy.deepcopy(v) for k, v in original.items() if k in REGISTER_FIELDS}
    if 'tags' in document:
        candidate['tags'] = copy.deepcopy(document['tags'])
    servers = [c for c in candidate['containerDefinitions'] if c['name'] == 'server']
    if len(servers) != 1 or servers[0]['image'] != expected_image:
        raise ValueError('고정 서버 이미지가 다릅니다')
    server = servers[0]
    if server.get('environmentFiles'):
        raise ValueError('외부 환경파일과 메일 설정 충돌을 먼저 확인해야 합니다')
    names = set(MAIL_ENV) | MAIL_SECRETS | IDENTITY_ENV
    if any((x['name'].startswith(('SPRING_MAIL_', 'IPGO_MAIL_')) or 'SMTP' in x['name'])
           and x['name'] not in names for x in server.get('environment', [])):
        raise ValueError('기존 추가 메일 옵션을 먼저 검토해야 합니다')
    server['environment'] = [x for x in server.get('environment', []) if x['name'] not in names]
    server['environment'].extend({'name': k, 'value': v} for k, v in MAIL_ENV.items())
    server['environment'].extend({'name': k, 'value': v} for k, v in mail_config.items())
    server['secrets'] = [x for x in server.get('secrets', []) if x['name'] not in names]
    server['secrets'].extend({'name': k, 'valueFrom': secret_arn} for k in sorted(MAIL_SECRETS))
    policy = {'Version': '2012-10-17', 'Statement': [{
        'Sid': 'ReadDevelopmentSmtpSecret', 'Effect': 'Allow',
        'Action': ['secretsmanager:GetSecretValue'], 'Resource': [secret_arn],
    }]}
    return candidate, policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--expected-definition', required=True)
    parser.add_argument('--expected-image', required=True)
    parser.add_argument('--secret-arn', required=True)
    parser.add_argument('--mail-config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.input.stat().st_mode & 0o077 or args.mail_config.stat().st_mode & 0o077:
        raise SystemExit('입력 파일 권한을 0600으로 제한해 주세요')
    raw = args.input.read_bytes()
    try:
        candidate, policy = prepare(json.loads(raw), expected_definition=args.expected_definition,
                                    expected_image=args.expected_image, secret_arn=args.secret_arn,
                                    mail_config=json.loads(args.mail_config.read_text()))
    except (ValueError, KeyError, TypeError):
        # 입력 정의/환경값을 예외 출력에 포함하지 않는다.
        raise SystemExit('후보 준비를 중단했습니다. 대상·이미지·정의 형식을 확인해 주세요') from None
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    # PR34의 Terraform 권한과 대조할 요구사항이다. 별도 IAM 쓰기용 실행기로 사용하지 않는다.
    artifacts = {'task-definition.json': candidate, 'required-secret-access.json': policy}
    hashes = {}
    for name, value in artifacts.items():
        data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        with (args.output_dir / name).open('xb') as output:
            output.write(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    manifest = {'input_sha256': hashlib.sha256(raw).hexdigest(), 'candidate_sha256': hashes,
                'source_definition': args.expected_definition, 'execution_role': candidate['executionRoleArn'],
                'aws_executed': False, 'secret_values_read': False, 'deployment_authorized': False}
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('메일 설정 후보 3개 파일 준비 완료. AWS 실행·Secret 값 조회·배포 없음.')


if __name__ == '__main__':
    main()

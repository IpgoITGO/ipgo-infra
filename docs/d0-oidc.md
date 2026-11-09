# D0 최소 권한 OIDC 설치와 중단

관련 IPGO-174 / Issue #42, Server IPGO-173 / Issue #153.
이 문서는 비활성 구현을 설명한다. IAM·DB 적용, ECR 게시, GitHub 설정과 D0 실행은 각각 실제 승인 후에 한다.
기존 조회 역할·기존 dev root와 Client 6c515b9·Server TD31·AI TD17은 변경하지 않는다.

## 구성과 허용 범위

독립 root `terraform/environments/d0-validation`은 기본 `enabled=false`, `runtime_enabled=false`다.
기존 dev state에 섞지 않고 같은 S3 backend의 `environments/d0-validation/terraform.tfstate`를 사용한다.
초기 설치 설정은 `enabled=true, runtime_enabled=false`다. 새 Secret container/로그그룹,
execution role+inline policy, install task role+inline policy, runtime/install task definition 총 8개를 추가한다.
설치 검증 뒤 `runtime_enabled=true`를 별도 plan/apply하면 새 runtime OIDC role+inline policy 2개를 추가한다.
Secret 값/DB password/서명 private key는 Terraform/state/plan 입력에 넣지 않는다.

| 역할 | 범위 |
|---|---|
| 기존 Infra apply OIDC | 최초 publish/plan/apply/install에만 사용. 기존 정책 변경 없음, 실제 유효 권한은 적용 전 확인 |
| 새 ipgo-dev-d0-runner-oidc | 고정 runtime revision RunTask, 개발 cluster tasks Describe, D0 태그 Stop, 고정 서비스 2개 Describe, 전용 log Get, execution role 1개 Pass |
| 새 ipgo-dev-d0-execution | ECS agent 전용: ECR 전용 repo pull, 새 Secret Get, 전용 log write. GetAuthorizationToken은 AWS 특성상 Resource * |
| 새 ipgo-dev-d0-install-task | 새 Secret ARN PutSecretValue만. 기존 master Secret Get 없음 |
| 기존 bootstrap execution role | install task의 기존 master Secret 주입과 이미지/로그 처리. 기존 정책 변경 없음 |

일상 task에는 task role이 없다. ECS Exec/임의 shell/SSM/서비스 배포/IAM 수정/Secret 직접 조회 권한을 주지 않는다.
RunTask IAM 조건에 subnet/SG 지원이 없어 네트워크·계정·SHA·이미지 digest·revision은 고정 공개키의
서명 manifest로 추가 확인한다. IAM 자체가 task override의 모든 문자열을 제한한다고 주장하지 않는다.

OIDC trust는 기존 provider를 재사용하며 aud=sts.amazonaws.com,
sub=`repo:IpgoITGO@346794439/ipgo-server@1430767744:environment:d0-validation` 한 개다.
GitHub immutable owner/repository ID 형식과 실제 token subject가 맞는지는 B단계에서 실측한다.
trust 불일치를 wildcard로 완화하지 않고 중단한다. 새 provider/기존 조회 role policy 수정은 없다.

## 단계별 승인과 workflow

새 `d0-infrastructure.yml`은 workflow_dispatch 전용이며 push/PR로 실제 적용하지 않는다.
기존 Infra dev environment의 자기승인·관리자 bypass 설정은 바꾸지 않는다. 새 Server runtime environment만 별도로 자기승인 금지를 요구한다.
모든 job은 dev SHA 일치·첫 시도·명시 확인문구와 개별 ENABLED flag, 기존 `dev` environment를 요구한다.
OIDC 전 실제 environment API를 읽어 승인자/dev 한 branch 정책을 확인하며 실패 시 중단한다.
GitHub token의 추가 권한은 해당 job의 Actions read, AWS OIDC write뿐이다. 장기 AWS key는 사용하지 않는다.

1. **소스 병합/이미지 게시 승인:** Server·Infra PR head와 CI를 확인하고 병합 후 SHA를 확정한다.
   `D0_PUBLISH_ENABLED=true`를 승인 후 설정한다. operation=publish, confirmation=PUBLISH_D0_IMAGE,
   expected_sha=Infra full SHA, helper_sha=Server dev에 포함된 full SHA로 실행한다.
   `ipgo-dev/database:d0-<Server SHA>` 새 tag만 게시한다. 조회 오류는 ImageNotFoundException 이외 모두 중단,
   기존 tag가 있으면 덮어쓰지 않는다. 실제 ECR digest/source/public-key hash artifact로 다음 단계를 고정한다.
2. **실제 plan 승인:** `D0_INFRA_ENABLED=true`, metadata-only `D0_TERRAFORM_JSON` 등록 후 operation=plan,
   confirmation=PLAN_D0. backend init/state lock에는 S3 쓰기가 생길 수 있다. AWS 리소스 적용은 없다.
   plan은 runner의 비공개 임시파일에 보관하고 일반 로그에는 허용 주소/행위/planSha256만 남긴다.
   이 digest는 입력과 전체 resource_changes를 포함한다. 전체 plan JSON은 NAS 고정 공개키로 AES-256-GCM/RSA-OAEP 봉인한 artifact로만 전달한다. NAS에서 `scripts/d0_plan_envelope.py unseal envelope.json /protected/plan.json --private-key /protected/existing-private.pem`으로 0600 신규 파일에 복호화해 실제 세부 내용을 검토한다. private key는 NAS 밖으로 보내지 않으며 단계 A에서는 일회 테스트 키만 사용한다.
3. **IAM·task 설치 적용 승인:** 같은 SHA/설정으로 operation=apply, confirmation=APPLY_D0,
   expected_plan_sha256=검토 digest 및 expected_iam_snapshot_sha256=검토 IAM fingerprint. 새로 만든 plan이 다르면 적용하지 않는다. 변경·교체·import·설치 객체 삭제는 거부한다.
   새 create 리소스의 주소/이름이 allowlist와 달라도 거부한다. 최초 8개 외 변경은 승인 범위 재검토가 필요하다.
4. **DB 최초 설치 승인:** `D0_INSTALL_ENABLED=true`, D0_INSTALL_JSON=installation output value,
   D0_SIGNED_INSTALL_MANIFEST=NAS에서 서명한 install 봉투(Base64) 등록. operation=install,
   confirmation=INSTALL_D0, expected_iam_snapshot_sha256=설치 전 검토 fingerprint, exact Infra/Server SHA를 사용한다. 고정 install revision 한 task만 실행한다.
   DB 새 schema/NOLOGIN role/원장/함수 생성, 새 password Secret 저장과 제한 로그인 활성화만 한다.
5. **검증·runtime 활성화 승인:** 새 DB role 직접 SELECT/UPDATE/DELETE/CREATE/기존 role 전환 거부와
   함수 성공을 실제 DB에서 확인한다. 기존 권한을 확대하지 않는다. runtime_enabled=true 실제 plan 2개만 검토·적용한다.
   Server의 새 d0-validation environment를 승인자≥1/자기승인금지/dev 한 branch로 등록하고
   runtime output과 날짜별 서명 봉투를 등록한다. D0_ENABLED=true 후 read-only만 승인 실행한다.
6. D0 prepare는 날짜/operation/합성 자료 영향과 별도 승인을 확인한 뒤 실행한다. 단계 A나 설치 성공이 D0 승인은 아니다.

Flags/GitHub 환경/Secrets는 이 PR이 생성·등록하지 않는다. 특히 실제 registry digest/task revision이 아직 없으면
예시값으로 서명·dispatch하지 않는다. source 병합만으로 기존 Server/AI 서비스가 갱신되지 않게 기존 배포 workflow의
변경 경로와 dispatch를 확인한다. 현재 Server 배포는 workflow_dispatch 전용이며 dev push로 서비스가 배포되지 않는다. 병합 시점에도 이를 재확인한다.

## Terraform 설정 형식

D0_TERRAFORM_JSON 최상위는 enabled, runtime_enabled, configuration 세 필드만 허용한다.
configuration은 account_id, image_uri(digest), bootstrap_execution_role_arn, master_secret_arn,
installation_log_group, db_host, db_name, subnet_ids, security_group_ids를 담는다.
실제 계정/내부 endpoint/ARN/tfvars/plan/state는 공개 repo나 PR에 게시하지 않는다.
기존 dev DB-task SG·public subnet을 재사용하며 task에 일시 public IPv4/ENI가 생긴다. inbound listener/port mapping은 없다. SG ingress, NAT, RDS 파라미터를 변경하지 않는다.
Secret은 새 `/ipgo/dev/d0-bootstrap` 하나만, log는 새 `/ipgo/dev/d0-validation` 하나만 만든다.
Secret은 prevent_destroy 및 복구 기간 30일, 새 log는 보존 30일이다.

## 실패와 복구

- plan/IAM/environment/서명/날짜 검증 실패: 적용·task 실행 없이 중단한다. 인증 복구를 반복하거나 기존 조회 권한을 늘리지 않는다.
- Terraform 부분 실패: runtime 활성화와 D0를 금지한다. 현재 state/실제 리소스와 직전 상태를 보호 저장한 후,
  승인된 복구 plan만 사용한다. 자동 destroy/기존 정책 덮어쓰기/기존 TD 변경은 없다.
- install 실패: 원장을 보존하고 관리자의 기존 migrator membership은 설치 transaction 안에서만 SET/INHERIT를 일시 사용하고 원래 옵션으로 복원한다. 새 bootstrap role만 NOLOGIN으로 되돌리기를 시도한다.
  Secret/DB가 비원자적이므로 실패 위치에 따라 새 Secret 또는 NOLOGIN 객체가 남는다.
  DB 연결 유실 시 NOLOGIN 성공도 미확인일 수 있다. `INSTALL_DEACTIVATION_UNCONFIRMED`는 관리자 확인 후 처리한다.
  기존 역할/비밀번호/자료를 초기화하지 않는다. 자세한 DB 경계는 Server `docs/development/d0-oidc.md`를 따른다.
- task 실패/timeout: 자신이 받은 task ARN만 StopTask. RunTask 응답 유실은 REQUESTED operation/clientToken을 보존한다.
  중복 task/업무 요청을 자동 재전송하지 않고 별도 조회/승인 후 상태를 확정한다.
- 긴급 사용 중지: Server D0_ENABLED=false, 새 task 중단. `runtime_enabled=false`만 바꿔
  revoke_runtime=true, PLAN_D0_REVOKE/APPLY_D0_REVOKE 및 검토 digest로 새 OIDC role/policy만 제거한다.
  `enabled=false`, destroy, Secret 삭제, DB DROP, 계정/업로드/입고 삭제는 승인 범위 밖이다.

## 검증과 남은 항목

```bash
python3 -m venv /tmp/d0-plan-venv
/tmp/d0-plan-venv/bin/pip install -r scripts/d0-plan-requirements.txt
/tmp/d0-plan-venv/bin/python -m unittest discover -s tests/d0 -p 'test_*.py'
terraform fmt -check -recursive
terraform -chdir=terraform/environments/d0-validation init -backend=false
terraform -chdir=terraform/environments/d0-validation validate
terraform -chdir=terraform/environments/d0-validation test
terraform -chdir=terraform/modules/d0-validation init -backend=false
terraform -chdir=terraform/modules/d0-validation validate
terraform -chdir=terraform/modules/d0-validation test
```

mock provider tests는 초기 8개/활성화 10개 경계와 기존 role 혼입 방지를 검사하며 실제 AWS 허용을 입증하지 않는다.
단계 A에는 실제 cloud plan, OIDC assume, ECR push, DB 설치, D0/LLM 호출과 다음날 업무 검증을 하지 않는다.
새 Secret·Fargate·로그·ECR 저장 및 전송은 AWS 비용이 추가된다. 적용 승인안에서 서울 리전 현재 요금으로 산정한다.
D0는 계산/LLM 0이어야 하지만 계정 전체 LLM cap을 다시 설정하지 않는다. 기존 real/지속 LLM/월 제한 OFF/시작 시각을 유지한다.


## IAM 사전 조회·스냅샷 (IPGO-175 / Issue #44)

기존 Infra OIDC 역할을 사용하며 IAM 권한은 이 변경에서 추가하지 않는다. `operation=preflight`,
`confirmation=PREFLIGHT_D0`, 정확 expected_sha, repository D0_INFRA_ENABLED=true로 읽기만 할 수 있다.
preflight는 Terraform backend/state lock, plan/apply, RunTask, ECR push, DB에 접근하지 않는다.
job-level if flags는 environment 변수가 아닌 repository variables로 등록하고 일회 검증 후 false로 마감한다.
GitHub 목록 조회는 전체 페이지와 total_count를 반드시 대조한다.

기존 `dev` environment 확인과 OIDC 발급 다음에, backend init보다 먼저 아래를 읽는다.

- STS 실제 계정/assumed role을 정확한 `ipgo-github-terraform-apply`와 대조한다.
- 그 역할 자신과 기존 `ipgo-dev-database-bootstrap-execution`, 새 D0 execution/install role의
  GetRole/trust/inline 정책 전체 페이지/attached 정책 전체 페이지/managed 정책 default version 원문과 boundary를 확인한다.
- runtime_enabled 또는 revoke에서만 새 runtime OIDC role도 관찰한다. 기존 역할의 NoSuchEntity는 실패다.
  새 생성 대상만 GetRole NoSuchEntity를 정상 부재로 기록한다. AccessDenied/다른 조회 오류를 부재로 바꾸지 않는다.
- attached/boundary는 GetPolicy/GetPolicyVersion이 필요하다. 정책/계정 전체 목록이나 이전 version을 일괄 조회하지 않는다.
  권한이 없으면 조회를 생략하거나 정책을 자동 추가하지 않고 중단한다.

원문/실패 단계/API/대상 요청은 runner 0600 파일에 쓰고 고정 NAS 공개키로 AES-256-GCM/RSA-OAEP 봉인한다.
공개 로그에는 성공 여부·fingerprint·고정 오류 코드만, artifact에는 `d0-iam-snapshot-envelope.json`만 올린다.
실패한 조회도 가능한 부분 스냅샷을 봉인·보존한 뒤 실패한다. 조회/암호화/업로드가 실패하면 backend/apply/install을 시작하지 않는다.
프로세스 강제 종료/runner 유실은 암호화 artifact 보존까지 보장할 수 없으며 이때도 적용을 성공으로 간주하지 않는다.
NAS에서 기존 `scripts/d0_plan_envelope.py unseal`과 원래 private key로 복호화한다. private key를 GitHub에 보내지 않는다.

IAM fingerprint는 source SHA·계정·역할 identity/trust/inline/managed default version·boundary·존재 상태·설정을 바인딩한다.
세션 이름/시각/runId는 fingerprint에서 제외하되 봉투 및 원문 context에는 남겨 provenance를 확인한다.
plan에는 같은 run의 완료된 IAM 스냅샷이 필요하며 새 role이 이미 있으면 create 충돌로 중단한다.
plan 봉투에는 IAM fingerprint를 함께 묶는다. apply/install은 추가 입력 `expected_iam_snapshot_sha256`와
당일 실제 조회 fingerprint가 일치해야 한다. plan의 expected_plan_sha256도 별도로 필요하다.
설치 전에는 새 role들이 실제 존재해야 한다. initial apply 후에는 존재 상태와 정책이 바뀌므로 새 fingerprint를 검토하고
설치 승인을 받는다. fingerprint를 맞추기 위해 임의로 최신 값을 재승인 없이 사용하지 않는다.

이 스냅샷은 여러 AWS 읽기의 관측 기록이며 원자적 IAM snapshot, IAM simulator, SCP/session policy까지 포함한
유효 권한 허용 증명이 아니다. source에서 자신의 role과 managed policy 원문 읽기는 확인되지 않았으므로 실제 IAM 조회가
거부될 수 있다. 그 경우 최소 읽기 범위만 별도 승인안으로 제시한다. 기존 조회 역할을 확대하지 않는다.
PR CI는 fake SDK/일회 RSA 키로 실패 차단과 암호화를 검증하고 AWS IAM에 접속하지 않는다.

참고: [AWS PowerUserAccess 원문](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/PowerUserAccess.html)은 IAM 전체 읽기를 보장하지 않는다. 추가 read 권한 필요 여부는 실제 preflight 오류와 정책 snapshot으로 구분한다.

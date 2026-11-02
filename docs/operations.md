# Terraform 운영

## HTTP에서 HTTPS로 전환하기

발급 완료된 기존 인증서 ARN을 유지하고 `AWS_API_DOMAIN_NAME`에 API의 전체 DNS 호스트를 설정합니다.
`AWS_ENABLE_HTTP_DEV_ENDPOINT=false`로 변경하면 HTTPS를 사용합니다. DNS 검증 CNAME은 갱신을 위해 유지합니다.
HTTPS 443을 먼저 만든 뒤 기존 HTTP 80 리스너의 동작만 redirect로 바꿉니다.
기존 http_dev 상태 주소는 moved 블록으로 http에 연결해 리스너를 삭제·재생성하지 않습니다.
ALB 기본 DNS 이름으로 들어온 HTTP 요청도 인증서와 일치하는 API 호스트로 이동합니다.

기존 plan 역할의 listener 조회 권한이 부족하면 권한을 확대하지 않고 보호된 dev 배포 workflow의
plan_only=true·confirmation=PLAN_DEV로 계획만 확인할 수 있습니다. dev 환경의 기존 승인은 유지됩니다.
같은 고정 SHA·변수에서 검토 후 plan_only=false·confirmation=APPLY_DEV로 적용합니다.
이 전환에서는 https_listener_only=true로 HTTPS 생성·HTTP 동작 수정 외 변경을 차단합니다.
요약에는 자원·동작·필드 이름만 출력하고 실제 plan/state 값은 공개하지 않습니다.

전환 전 listener·인증서·서버 이미지/실행 수·변수 값을 비공개로 보존합니다.
실제 TLS 인증서와 이름 검증, HTTP redirect, Swagger 화면/문서/정적 파일,
헬스·기존 인증/CSRF 응답과 현재 서버 이미지·수량 유지까지 확인합니다.
복구는 임시 HTTP 모드로 돌아간 새 plan을 별도 검토해 적용하며, 서버 코드·DB는 되돌리지 않습니다.

## 서버가 처음 켜질 때의 대기 시간

서버 서비스는 새 task 시작 후 180초 동안 초기 헬스 실패로 조기 종료하지 않도록 기다립니다.
Swagger 추가 배포에서 앱 기동이 약 67초 걸려 기존 60초 유예와 ALB 상태 회복 시간이 충돌했습니다.
실제 배포에서 같은 task definition·이미지·실행 수를 유지한 채 시작 유예만 180초로 조정했고,
이 코드도 그 값에 맞춥니다. 헬스 체크와 deployment circuit breaker/rollback은 유지합니다.

이 값의 변경은 새 deployment를 만들지 않습니다. 기존 배포가 진행 중이면 같은 run과
deployment를 관측하고 target healthy·rollout 완료를 확인합니다. Terraform plan에서 다른 변경이
없음을 확인하며, 이미 조정된 실행 설정과 코드가 같다면 추가 apply로 서버를 다시 바꾸지 않습니다.
복구 시 이전 실행 정의와 함께 변경 전 유예 값을 확인하고, 안정화 이후 승인된 값으로 맞춥니다.

## 인증서 발급 전 임시 HTTP 개발 주소

연결 테스트를 먼저 해야 하는 경우에만 사용자 승인 후 저장소 변수
`AWS_ENABLE_HTTP_DEV_ENDPOINT=true`를 설정합니다. plan/apply는 이 모드에서 인증서 ARN 전달을
생략하고 `enable_http_dev_endpoint=true`를 전달합니다. 기본값은 false이며 기존 초기 구성은 유지합니다.
HTTP 80 리스너 한 개가 기존 서버 대상 그룹으로 전달하고, ECS의 서버 LB 연결을 활성화합니다.
서버 이미지·수량의 ignore_changes와 기존 네트워크·DB·Secret 값은 유지합니다.

실행 중인 이전 apply가 환경 승인 대기라면 대상 SHA와 미실행 상태를 확인·보존하고 취소한 뒤
새 HTTP 계획의 고정 SHA만 적용합니다. 실제 plan에서 HTTP 리스너 생성·서버 LB 연결 이외 변경,
자원 삭제·교체가 있으면 적용 전에 별도 검토합니다.
적용 후 대상 그룹 healthy·기존 이미지와 수량 유지·외부 HTTP health 응답을 확인합니다.
Secure 쿠키 설정은 유지되므로 HTTP 주소의 검증 범위는 연결과 인증 실패 응답입니다.
실제 계정 정보 전송과 브라우저 로그인·갱신은 HTTPS 주소에서 검증합니다.

HTTPS 전환 시 ACM ISSUED를 확인한 다음 이 변수를 false로 변경하거나 제거하고 새 plan을 검토합니다.
인증서 변수는 그대로 유지합니다. 임시 HTTP 전달 리스너가 제거되고 HTTPS 리스너와 HTTP redirect가
생성되며 기존 ECS 대상 그룹 연결은 유지됩니다. HTTP 단계 성공을 HTTPS 통합 완료로 보고하지 않습니다.
임시 연결 복구는 인증서 변수를 비운 상태에서 HTTP opt-in도 끈 계획을 별도 검토해 적용합니다.
기존 요청을 되돌릴 때 인증서 변수·HTTP 모드 두 값을 함께 확인합니다.

## 개발 API HTTPS 인증서 연결

서울 리전 ACM에서 API의 전체 도메인 이름에 대한 DNS 검증을 완료한 뒤,
저장소 Actions variable `AWS_ACM_CERTIFICATE_ARN`에 해당 인증서 ARN을 설정합니다.
plan/apply workflow 모두 임시 HTTP 모드가 꺼져 있고 값이 있을 때만 `TF_VAR_certificate_arn`으로 전달합니다.
값이 없으면 Terraform의 기존 null 기본값을 사용해 인증서 없는 초기 구성을 유지합니다.
개인 도메인과 실제 ARN은 공개 소스에 넣지 않습니다.

외부 DNS에는 API 호스트를 기존 ALB DNS로 연결하는 CNAME과 ACM이 발급한 검증 CNAME을
각각 등록합니다. 검증 CNAME은 갱신을 위해 유지합니다. 인증서가 `ISSUED`인지 확인하고
고정된 코드 SHA의 plan에서 HTTPS/HTTP 리스너 생성과 기존 서버 서비스의 대상 그룹 연결만
변경되는지 검토합니다. 다른 변경이 있으면 적용 전에 범위를 다시 확인합니다.
plan 요약에는 변경 자원 주소·동작만 출력하며 state/plan의 실제 값은 공개하지 않습니다.

apply 전 현재 서버 Task Definition·이미지·desired count와 ALB 구성을 비공개 위치에 보존하고
사용자 승인을 받습니다. 서비스의 `task_definition`·`desired_count` ignore_changes는 유지합니다.
적용 후 기존 최신 이미지와 실행 수가 유지되는지, 대상 그룹 healthy, HTTP→HTTPS 리다이렉트,
호스트 이름과 일치하는 TLS 인증서 및 `/actuator/health` 실제 응답을 확인합니다.
앱 healthCheck가 없으면 ECS 앱 컨테이너 `UNKNOWN`을 별도로 기록합니다.

복구 시 승인된 이전 구성으로 plan을 만들어 리스너와 서비스 LB 연결을 되돌립니다.
인증서 변수 제거만으로 다음 apply가 리스너를 없앨 수 있으므로 먼저 영향과 plan을 검토합니다.
이 작업은 DB migration·NAT·Secret 값·다른 서비스 배포를 포함하지 않습니다.

## 현재 단계

현재 configuration은 검토와 검증용이며 AWS에 적용되지 않았습니다. 실제 apply 전에는 대상 AWS 계정과 `ap-northeast-2` 리전을 읽기 호출로 다시 확인합니다.

## State bootstrap

`terraform/bootstrap`은 versioning과 암호화를 사용하는 S3 state bucket을 만듭니다. 최초 한 번만 local state로 적용한 뒤 dev root module의 S3 backend를 초기화합니다.

State에는 민감한 값이 포함될 수 있으므로 bucket 이름과 실제 backend 설정은 공개 저장소에 commit하지 않습니다. `backend.hcl.example`을 복사한 `backend.hcl`은 Git에서 제외됩니다.

Bootstrap은 GitHub OIDC provider와 다음 role도 만듭니다.
Role trust policy는 GitHub의 `use_immutable_subject` 형식에 맞춰 organization과 repository의
숫자 ID를 사용하므로, 저장소 이름이 이전되거나 재사용돼도 기존 역할을 인수할 수 없습니다.

| role | 사용 주체 | 경계 |
|---|---|---|
| `ipgo-github-terraform-plan` | `ipgo-infra`의 `dev-plan` Environment | AWS metadata와 dev state 읽기 |
| `ipgo-github-terraform-apply` | `ipgo-infra`의 보호된 `dev` Environment | dev 인프라 변경 |
| `ipgo-github-server-deploy` | `ipgo-server`의 보호된 `dev` Environment | Server ECR/ECS 배포 |
| `ipgo-github-ai-deploy` | `ipgo-ai`의 보호된 `dev` Environment | AI ECR/ECS 배포 |

대상 AWS 계정에 `token.actions.githubusercontent.com` provider가 이미 있으면
`github_oidc_provider_arn`에 기존 ARN을 전달해 중복 생성을 피합니다.

## 최초 bootstrap

로컬의 승인된 AWS SSO profile로 계정과 Region을 먼저 확인합니다. Access Key를 저장소나 GitHub에
넣지 않습니다.

```bash
aws sts get-caller-identity
cp terraform/bootstrap/bootstrap.auto.tfvars.example terraform/bootstrap/bootstrap.auto.tfvars
cp terraform/bootstrap/bootstrap_override.tf.example terraform/bootstrap/bootstrap_override.tf
terraform -chdir=terraform/bootstrap init -reconfigure
terraform -chdir=terraform/bootstrap plan -out=bootstrap.tfplan
terraform -chdir=terraform/bootstrap apply bootstrap.tfplan
terraform -chdir=terraform/bootstrap output
```

출력된 bucket 이름을 `terraform/bootstrap/backend.hcl`에 넣은 뒤 local bootstrap state를 즉시 같은
bucket으로 옮깁니다. migration 전에는 local state를 별도 보안 경로에 백업하고,
`terraform/bootstrap/bootstrap_override.tf`를 삭제해 원래 S3 backend 선언을 복원합니다.

```bash
cp terraform/bootstrap/backend.hcl.example terraform/bootstrap/backend.hcl
terraform -chdir=terraform/bootstrap init -migrate-state -backend-config=backend.hcl
terraform -chdir=terraform/bootstrap state list
```

Bootstrap state도 민감할 수 있으므로 공개 artifact에 올리지 않습니다. migration과 `state list`가
성공하기 전에는 local state를 삭제하지 않습니다.

## GitHub Environment 설정

세 저장소에 `dev` Environment를 만들고 현재 관리자를 required reviewer로 지정합니다. Infra에는
reviewer 없는 `dev-plan` Environment도 만듭니다. Environment-level variable은 job-level 조건보다
늦게 제공되므로 다음 값은 GitHub Repository variable로 설정합니다.

| 저장소 | 변수 |
|---|---|
| `ipgo-infra` | `AWS_ACCOUNT_ID`, `AWS_PLAN_ROLE_ARN`, `AWS_APPLY_ROLE_ARN`, `TF_STATE_BUCKET` |
| `ipgo-server` | `AWS_ACCOUNT_ID`, `AWS_DEPLOY_ROLE_ARN` |
| `ipgo-ai` | `AWS_ACCOUNT_ID`, `AWS_DEPLOY_ROLE_ARN` |

ARN과 bucket 이름은 인증 비밀값은 아니지만 공개 workflow log에 출력하지 않습니다. AWS Access Key와
Secret Access Key는 GitHub Secret으로도 만들지 않습니다.

## Runtime Secret 준비

Terraform은 Secret container만 만들고 값은 만들지 않습니다. 실제 값은 승인된 운영자가 AWS
Secrets Manager에 직접 입력합니다.

- `/ipgo/dev/server-database`: `{"url":"jdbc:postgresql://...","username":"...","password":"..."}`
- `/ipgo/dev/server-jwt-secret`: Spring JWT 서명에 사용하는 충분히 긴 무작위 원문
- `/ipgo/dev/ai-database`: `{"url":"postgresql://..."}`. 조회 전용 login role만 사용
- `/ipgo/dev/ai-openai-api-key`: OpenAI API key 원문

FastAPI login role에는 승인된 `ai_*_v1` view의 `SELECT`만 부여합니다. Spring runtime login role에는
업무 DML만 부여하고 schema 변경은 별도 migration role로 실행합니다. 실제 사용자·비밀번호·grant는
Server migration과 함께 검증한 뒤 입력하며 이 저장소나 Actions log에 남기지 않습니다.

RDS snapshot, role bootstrap, Flyway 적용과 복구 순서는 [RDS migration 운영 런북](rds-migration.md)을
따릅니다. Spring runtime task가 직접 Flyway를 실행하지 않도록 별도 one-off migration 경로를 먼저
준비해야 합니다.

## 검증 순서

```bash
terraform fmt -check -recursive
terraform -chdir=terraform/bootstrap init -backend=false
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/environments/dev init -backend=false
terraform -chdir=terraform/environments/dev validate
```

AWS 읽기 권한과 backend가 준비된 뒤에만 plan을 생성합니다.

```bash
cp terraform/environments/dev/backend.hcl.example terraform/environments/dev/backend.hcl
cp terraform/environments/dev/dev.auto.tfvars.example terraform/environments/dev/dev.auto.tfvars
terraform -chdir=terraform/environments/dev init -backend-config=backend.hcl
terraform -chdir=terraform/environments/dev plan -out=dev.tfplan
```

Plan 파일은 Secret을 포함할 수 있으므로 commit하거나 공개 artifact로 올리지 않습니다.

## Dev 월간 비용 가드레일

2026-10-29 AWS 공식 Pricing API의 서울 리전 단가와 월 730시간을 기준으로 한 초기 추정입니다.
가격은 바뀔 수 있으므로 apply 직전에 다시 조회합니다.

| 항목 | 계산 | 월 예상 |
|---|---:|---:|
| ALB | `$0.0225 × 730시간` | `$16.43` |
| ALB public IPv4 최소 2개 | `$0.005 × 2 × 730시간` | `$7.30` |
| RDS `db.t4g.micro` | `$0.025 × 730시간` | `$18.25` |
| RDS GP3 20GiB | `$0.131 × 20GiB` | `$2.62` |
| 기본 고정비 |  | **약 `$44.60`** |

NAT Gateway를 활성화하면 시간당 `$0.059`, 월 약 `$43.07`이 추가되므로 월 50달러 dev 한도에서는
기본값을 `false`로 유지합니다. 세 ECS task를 동시에 실행할 때 Fargate와 task public IPv4의 합계는
시간당 약 `$0.12856`이며, ALB LCU·로그·데이터 전송을 제외하면 월 약 42시간이 남는 예산입니다.
실제 운영은 여유분을 두고 월 25시간 이하를 1차 기준으로 사용하며 Cost Explorer에서 누적액을
확인합니다.

## Apply 승인 조건

다음을 정리해 사용자 승인을 받은 뒤에만 apply합니다.

1. 생성·변경·삭제되는 자원
2. 월별 고정 비용이 예상되는 ALB와 RDS, 선택적으로 활성화하는 NAT Gateway, 실행 시간만큼 과금되는 ECS
3. 데이터와 사용자 영향
4. 검증 결과
5. 실패 시 rollback 또는 destroy 범위

초기 apply는 ECS service를 desired count 0으로 생성합니다. Secret 값, DB role/view와 image가 준비된
뒤 Server·AI 저장소의 수동 deploy workflow로 task revision을 등록하고 desired count를 1로 올립니다.
Spring은 공유 session 저장소가 아직 없으므로 dev task 수를 1로 유지합니다.

## Rollback

- 애플리케이션: ECS service를 직전 정상 task definition revision으로 되돌리고 desired count를 1로 유지합니다.
- 신규 서비스 중단: 해당 ECS service desired count를 0으로 내립니다.
- 인프라: 승인된 이전 Git commit으로 새 plan을 만들고 데이터 자원 삭제 여부를 따로 확인합니다.
- RDS와 S3는 장애 rollback 과정에서 자동 삭제하지 않습니다.

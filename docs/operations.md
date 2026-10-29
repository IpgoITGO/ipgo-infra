# Terraform 운영

## 현재 단계

현재 configuration은 검토와 검증용이며 AWS에 적용되지 않았습니다. 실제 apply 전에는 대상 AWS 계정과 `ap-northeast-2` 리전을 읽기 호출로 다시 확인합니다.

## State bootstrap

`terraform/bootstrap`은 versioning과 암호화를 사용하는 S3 state bucket을 만듭니다. 최초 한 번만 local state로 적용한 뒤 dev root module의 S3 backend를 초기화합니다.

State에는 민감한 값이 포함될 수 있으므로 bucket 이름과 실제 backend 설정은 공개 저장소에 commit하지 않습니다. `backend.hcl.example`을 복사한 `backend.hcl`은 Git에서 제외됩니다.

Bootstrap은 GitHub OIDC provider와 다음 role도 만듭니다.

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
- `/ipgo/dev/ai-database`: `{"url":"postgresql://..."}`. 조회 전용 login role만 사용
- `/ipgo/dev/ai-openai-api-key`: OpenAI API key 원문

FastAPI login role에는 승인된 `ai_*_v1` view의 `SELECT`만 부여합니다. Spring runtime login role에는
업무 DML만 부여하고 schema 변경은 별도 migration role로 실행합니다. 실제 사용자·비밀번호·grant는
Server migration과 함께 검증한 뒤 입력하며 이 저장소나 Actions log에 남기지 않습니다.

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

## Apply 승인 조건

다음을 정리해 사용자 승인을 받은 뒤에만 apply합니다.

1. 생성·변경·삭제되는 자원
2. 월별 고정 비용이 예상되는 NAT Gateway, ALB, RDS, ECS
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

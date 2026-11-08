# Ipgo Infra

개발 서버의 단일 호스트 전환·비용·장애 알림·복구 절차는 [운영 문서](docs/onebox.md)를 참고합니다.

인증 메일 설정 후보와 별도 적용 승인·검증·복구 절차는 [개발 메일 준비](docs/dev-mail-preparation.md)를 봅니다.

IpgoITGO의 AWS 공통 인프라를 Terraform으로 관리하는 공개 저장소입니다. Spring Boot API, FastAPI 계산 엔진과 공통 데이터 계층이 사용하는 기반 자원을 정의합니다.

> AWS 개발 환경은 운영 중입니다. 현재 단일 서버·CloudFront 구성과 실제 적용 여부는 [운영 문서](docs/onebox.md)를 기준으로 확인합니다. 개발용 SQS와 DLQ는 실제 엔진 결과 전달을 위해 메시지 최대 크기 1MiB를 사용하도록 준비합니다.

## 확정된 서비스 경계

- Spring Boot는 업무 DB를 소유하고 조회·등록·수정, 상태 관리와 결과 저장을 담당합니다.
- FastAPI는 승인된 계산용 view와 필요한 테이블을 `SELECT`만 할 수 있습니다.
- 긴 정제·계산·백테스트는 SQS 비동기 작업으로 처리합니다.
- 짧은 시나리오·AI 인사이트는 ECS 내부 HTTP로 호출합니다.
- 업로드 원본은 S3에 저장합니다. Spring은 읽기·쓰기, FastAPI는 읽기 권한만 가집니다.
- 실제 DB 자격 증명과 API key는 Secrets Manager에서 관리하고 저장소에는 기록하지 않습니다.
- GitHub Actions는 OIDC 임시 자격 증명만 사용하며 장기 AWS Access Key를 저장하지 않습니다.

자세한 내용은 [아키텍처](docs/architecture.md)와 [데이터 접근 계약](docs/decisions/0002-data-access-contract.md)을 확인합니다.

## 저장소 구조

```text
terraform/
├─ bootstrap/          # Terraform remote state용 S3 bucket
├─ environments/dev/  # 개발 환경 root module
└─ modules/
   ├─ network/         # VPC, subnet, NAT
   ├─ storage/         # 업로드 S3
   ├─ messaging/       # SQS와 DLQ
   ├─ database/        # private RDS PostgreSQL
   ├─ compute/         # ECS, ECR, ALB, Service Connect 기반
   └─ identity/        # Spring/FastAPI task role
docs/
└─ decisions/          # 변경 이유와 계약 기록
```

## 사전 요구 사항

- Terraform 1.10 이상 2.0 미만
- AWS provider 6.x
- AWS 배포 리전: 기본 제안 `ap-northeast-2`
- AWS 인증: 로컬은 승인된 profile, CI는 GitHub OIDC 역할

## 로컬 검증

AWS 자격 증명 없이 형식과 정적 구성을 확인할 수 있습니다.

```bash
terraform fmt -check -recursive
terraform -chdir=terraform/bootstrap init -backend=false
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/environments/dev init -backend=false
terraform -chdir=terraform/environments/dev validate
```

`plan`과 `apply` 절차는 [운영 문서](docs/operations.md)를 따릅니다. 사용자 승인 전에는 `terraform apply`를 실행하지 않습니다.

개발용 Gmail SMTP secret의 저장 경로·권한·적용 경계는 [메일 설정 운영 문서](docs/server-mail.md)를 참고합니다. Terraform은 secret의 메타데이터만 관리하며 앱 비밀번호와 서버 메일 설정 배포는 포함하지 않습니다.

최초 bootstrap은 state bucket과 GitHub OIDC 역할을 만듭니다. 이후 `Terraform dev plan`은
같은 저장소의 `dev` PR만, `Terraform dev apply`는 보호된 GitHub `dev` Environment에서 수동
확인값과 reviewer 승인을 모두 통과한 경우만 실행됩니다. 초기 ECS service의 task 수는 0이므로
image와 Secret을 준비하기 전에 애플리케이션이 잘못 기동되지 않습니다.

## 비용 주의

개발 환경은 월 50달러 한도를 지키기 위해 NAT Gateway를 기본으로 만들지 않습니다. ECS task는 필요한
시간에만 public subnet에서 공인 IP를 받아 외부 통신하고, 보안 그룹은 ALB→Spring Boot와
Spring Boot→FastAPI 진입만 허용합니다. ALB와 RDS는 생성된 동안 고정 비용이 발생하므로 실제
apply 전에 예상 비용과 종료 시점을 검토해야 합니다.

## 개발 배포 task 검증 읽기 권한

bootstrap의 Server/AI GitHub 배포 역할에 `ecs:ListTasks`와 `ecs:DescribeTasks`를
추가하는 코드입니다. `ArnEquals ecs:cluster`로 기존 개발 cluster만 허용하며 새 쓰기 권한은
추가하지 않습니다. 앱 저장소의 배포 전후 task/image/HEALTHY 확인에 필요합니다.
실제 IAM 적용은 하지 않았습니다. 별도 승인된 bootstrap plan/apply로 기존 변경과 영향이
없는지 검토해야 하며, 이번 변경만 필요하다면 해당 최소 정책 delta를 확인합니다.
역할 policy 제거/복구 시 task 검증은 조회 단계에서 실패할 수 있으므로 앱 workflow 적용 순서와
함께 검토합니다. 로컬 검증은 backend 없는 init과 validate/fmt이며 실제 IAM 허용 결과를
검증한 것은 아닙니다.

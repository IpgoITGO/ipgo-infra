# Ipgo Infra

IpgoITGO의 AWS 공통 인프라를 Terraform으로 관리하는 공개 저장소입니다. Spring Boot API, FastAPI 계산 엔진과 공통 데이터 계층이 사용하는 기반 자원을 정의합니다.

> 현재 상태는 **코드 준비 단계**입니다. 이 저장소의 Terraform은 아직 AWS에 적용되지 않았고 AWS 리소스도 생성하지 않았습니다.

## 확정된 서비스 경계

- Spring Boot는 업무 DB를 소유하고 조회·등록·수정, 상태 관리와 결과 저장을 담당합니다.
- FastAPI는 승인된 계산용 view와 필요한 테이블을 `SELECT`만 할 수 있습니다.
- 긴 정제·계산·백테스트는 SQS 비동기 작업으로 처리합니다.
- 짧은 시나리오·AI 인사이트는 ECS 내부 HTTP로 호출합니다.
- 업로드 원본은 S3에 저장합니다. Spring은 읽기·쓰기, FastAPI는 읽기 권한만 가집니다.
- 실제 DB 자격 증명과 API key는 Secrets Manager에서 관리하고 저장소에는 기록하지 않습니다.

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

## 비용 주의

개발 환경 코드에는 private ECS task의 외부 통신을 위한 NAT Gateway, RDS, ALB가 포함됩니다. 이 자원은 생성된 동안 고정 비용이 발생할 수 있으므로 실제 apply 전에 예상 비용과 종료 시점을 검토해야 합니다.

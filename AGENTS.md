# Ipgo Infra 개발 지침

- 적용 범위: 이 저장소 전체
- 이 저장소는 IpgoITGO의 AWS 공통 인프라와 배포 운영 문서를 관리합니다.
- 애플리케이션 소스와 실제 Secret 값은 저장하지 않습니다.

## 개발 흐름

- 초기 저장소 부트스트랩 이후 변경은 최신 `dev`에서 `feature/<issue-number>-<description>` 브랜치를 만듭니다.
- `dev` 대상 PR에서 Terraform plan과 문서 영향을 검토합니다.
- `main` 변경은 `dev → main` PR로만 진행합니다.
- `main` 직접 push, force push와 승인되지 않은 `terraform apply`를 금지합니다.
- 운영 apply는 대상·영향·검증·되돌리기 방법을 정리하고 사용자 승인을 받은 뒤 실행합니다.

## 책임 경계

- Infra: VPC, IAM, RDS, S3, SQS, ECS 기반, ECR, ALB, DNS, Secret 리소스, 관측성
- Server: Spring Boot 코드, Flyway migration, Docker image, 업무 데이터 쓰기
- AI: FastAPI 코드, 계산 엔진, Docker image, 계산용 DB 조회
- Client: React 코드, Vercel 배포, 브라우저 API 연동

### 앞으로 새로 생기는 인프라 작업

- 서비스 레포에서 발견한 인프라 요구도 이 저장소의 작업으로 분리합니다. AWS 자원·접근 권한·
  Secret 리소스·백업·관측성과 공통 운영 정책의 작업 정의·설정 코드·검증·운영 문서를 여기서 관리합니다.
- 서비스 기능과 함께 바뀌면 각 레포의 Issue·PR을 연결하고 선행 조건·적용 순서를 명시합니다.
  예: DB 테이블 변경은 Server, DB 인스턴스 용량·백업 설정은 Infra가 맡습니다.
- 서비스별 Docker image·배포 workflow, Server의 Flyway, Client의 Vercel 배포·API 연결은
  각 서비스 레포에 둡니다. 공통 인프라 정책이 바뀌는 부분만 Infra에서 다룹니다.
- 이 기준으로 완료·종료된 작업이나 과거 Issue·PR을 다시 열거나 기존 코드를 옮기지 않습니다.
  기존 작업에 새 인프라 요구가 생기면 그 부분부터 분리합니다. 실제 배포·권한 변경·Secret 값
  주입·비용 발생은 기존 승인 절차를 따르며, Secret 값은 이 저장소에 저장하지 않습니다.

## 안전

- `.tfvars`, state, plan, AWS 자격 증명, 비밀번호, token과 Secret 값을 commit하지 않습니다.
- 공개 저장소임을 전제로 account ID, 내부 endpoint와 개인 식별 정보를 불필요하게 기록하지 않습니다.
- CI는 GitHub OIDC로 AWS 역할을 사용하고 장기 Access Key를 저장하지 않습니다.
- `terraform apply`, import, destroy, state 변경은 실행 전 별도 승인이 필요합니다.
- 중요한 인프라 변경은 복구 방법과 데이터 보존 영향을 PR에 기록합니다.

## 검증

변경 범위에 따라 다음을 실행합니다.

```bash
terraform fmt -check -recursive
terraform -chdir=terraform/bootstrap init -backend=false
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/environments/dev init -backend=false
terraform -chdir=terraform/environments/dev validate
```

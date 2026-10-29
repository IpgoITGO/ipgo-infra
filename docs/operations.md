# Terraform 운영

## 현재 단계

현재 configuration은 검토와 검증용이며 AWS에 적용되지 않았습니다. 실제 apply 전에는 대상 AWS 계정과 `ap-northeast-2` 리전을 읽기 호출로 다시 확인합니다.

## State bootstrap

`terraform/bootstrap`은 versioning과 암호화를 사용하는 S3 state bucket을 만듭니다. 최초 한 번만 local state로 적용한 뒤 dev root module의 S3 backend를 초기화합니다.

State에는 민감한 값이 포함될 수 있으므로 bucket 이름과 실제 backend 설정은 공개 저장소에 commit하지 않습니다. `backend.hcl.example`을 복사한 `backend.hcl`은 Git에서 제외됩니다.

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

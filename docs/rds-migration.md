# RDS migration 운영 런북

이 문서는 `ap-northeast-2`의 private RDS PostgreSQL `ipgo-dev-postgres`에 Server 저장소의
Flyway migration을 적용할 때 사용하는 승인·검증·복구 기준입니다. 비밀번호, endpoint, Secret 값과
AWS account ID는 기록하지 않습니다.

## 역할 경계

| 역할 | 용도 | 금지 |
|---|---|---|
| RDS bootstrap administrator | 최초 login role 생성과 소유권 이전 | 애플리케이션 runtime |
| `ipgo_migrator` | Flyway schema 변경과 객체 소유 | Spring·FastAPI runtime |
| `ipgo_server` | Spring 업무 테이블 DML | Flyway·DDL |
| `ipgo_ai_reader` | 승인된 `ai_*_v1` view 조회 | 원본 table 조회·DML·DDL |

Spring runtime task에서는 Flyway를 비활성화합니다. migration은 같은 VPC에서 실행되는 별도
one-off task만 사용하고, 작업이 끝나면 task가 정상 종료돼야 합니다.

## 실행 전 필수 게이트

- [ ] Infra `dev`가 승인된 Terraform plan으로 apply되어 RDS 상태가 `available`임
- [ ] 서울 리전에서 주문 가능한 PostgreSQL 16.x와 `db.t4g.micro`·GP3 조합을 다시 확인함
- [ ] Server `dev` commit으로 만든 immutable DB image에 V1~V13 migration과 `database/bootstrap/create_roles.sql`이 포함됨
- [ ] one-off role bootstrap·Flyway task가 private RDS에 연결되며 runtime service와 분리됨
- [ ] Spring task에 `SPRING_FLYWAY_ENABLED=false`가 설정됨
- [ ] 세 login role의 인증정보가 승인된 절차로 Secrets Manager에 설정됨
- [ ] Server·AI ECS service의 desired count가 0임
- [ ] RDS deletion protection과 final snapshot이 활성화됨
- [ ] 공식 AWS MCP의 `GetCallerIdentity`로 승인된 계정과 서울 리전을 다시 확인함

위 항목 중 하나라도 충족되지 않으면 snapshot이나 migration을 시작하지 않습니다.

## 1. Migration 전 수동 snapshot

1. `DescribeDBInstances`로 대상 identifier, `available` 상태, engine version, Single-AZ 여부를 확인합니다.
2. UTC 기준 `ipgo-dev-postgres-pre-v13-YYYYMMDDHHMMSS` 이름으로 `CreateDBSnapshot`을 한 번 호출합니다.
3. 같은 snapshot identifier를 `DescribeDBSnapshots`로 조회해 `available`이 될 때까지 기다립니다.
4. source DB identifier, engine version, 생성 시각과 `available` 상태를 작업 기록에 남깁니다.

Single-AZ snapshot 생성 중에는 짧은 I/O 중단이 생길 수 있으므로 service를 먼저 0으로 유지합니다.
수동 snapshot은 명시적으로 삭제할 때까지 유지되며 삭제는 별도 승인을 받습니다.

## 2. Role bootstrap과 V1~V13 적용

1. RDS bootstrap administrator를 사용하는 one-off task에서 Server 저장소의
   `database/bootstrap/create_roles.sql`을 실행합니다. SQL은 role만 만들고 비밀번호를 출력하거나
   저장하지 않습니다.
2. 승인된 별도 절차로 세 login role의 인증정보를 설정합니다. Secret 값은 task log와 명령 인수에
   남기지 않습니다.
3. `ipgo_migrator` 인증정보를 사용하는 one-off Flyway task에서 target V13으로 `migrate`를 실행합니다.
4. Flyway task의 종료 코드가 0인지 확인하고 `flyway_schema_history`의 V1~V13이 모두 success인지
   확인합니다. 실패한 migration을 `repair`로 숨기지 않습니다.
5. migration task definition과 실행한 DB image digest를 작업 기록에 남깁니다.

실행은 `Database dev migration` workflow에서만 시작합니다. 승인된 수동 snapshot identifier,
Server 저장소의 현재 `dev` HEAD와 일치하는 40자리 commit SHA, 확인 문구 `MIGRATE_DEV_V13`을 모두 입력해야 합니다.
workflow는 snapshot source·상태와 세 ECS service의 desired count 0을 재검증한 뒤 DB 전용 immutable
image를 만들고 `bootstrap → migrate → verify` task를 순서대로 실행합니다. 앞 단계가 실패하면 다음
단계를 시작하지 않습니다.

현재 AWS에는 신규 빈 DB가 생성될 예정이므로 최초 실행은 V1부터 V13까지 적용합니다. 이후 V9 데이터가
있는 환경을 승격할 때도 같은 task를 사용하며, repository의 PostgreSQL 검증 스크립트가 증명한
V9→V13 upgrade 경로를 따릅니다.

## 3. 적용 후 검증

| 검증 | 성공 기준 |
|---|---|
| schema version | `flyway_schema_history` 최신 성공 version이 13 |
| 업무 table | 18개 table 존재 |
| AI view | `ai_product_daily_stocks_v1` 존재 |
| Spring 권한 | 업무 DML 성공, DDL과 Flyway history 변경 실패 |
| FastAPI 권한 | AI view `SELECT` 성공, 원본 table 조회와 DML·DDL 실패 |
| tenant 무결성 | 서로 다른 회원 데이터의 교차 연결과 소유자 변경 실패 |

쓰기 검증은 transaction 안에서 실행한 뒤 rollback합니다. 모든 검증이 끝난 후에만 승인된 Server·AI
image를 배포하고 필요한 service의 desired count를 1로 올립니다.

## 4. 실패와 복구

### 애플리케이션만 실패

V10~V13은 additive migration이므로 schema를 내리지 않고 ECS service를 0으로 내린 뒤 직전 정상
task definition으로 되돌립니다. 이미 적용된 migration 파일을 수정하거나 down migration을 만들지
않습니다.

### Migration 또는 데이터 검증 실패

1. Server·AI service를 0으로 유지하고 실패한 DB를 보존합니다.
2. 원인과 `flyway_schema_history` 상태를 기록하고 추가 쓰기를 막습니다.
3. migration 전 snapshot을 새 identifier로 복원합니다. RDS snapshot은 기존 DB 위에 덮어쓸 수 없고
   항상 새 DB instance를 만듭니다.
4. 복원 DB가 `available`이고 storage initialization이 끝났는지 확인합니다.
5. 검증이 끝난 뒤에만 Secret endpoint 전환을 별도로 승인받습니다.
6. 원본 DB와 snapshot 삭제는 데이터 보존 확인 후 별도 승인으로 처리합니다.

AWS 공식 문서:

- [RDS snapshot에서 복원](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_RestoreFromSnapshot.html)
- [Single-AZ snapshot의 I/O 영향](https://aws.amazon.com/blogs/database/implementing-a-disaster-recovery-strategy-with-amazon-rds/)

## 현재 상태

- AWS bootstrap state와 GitHub OIDC 역할: 준비됨
- VPC, private RDS, ECR, ECS와 runtime Secret container: 생성됨
- Server·AI service desired count: 0
- migration 전 수동 snapshot: 생성 후 `available` 확인됨
- runtime Secret 값과 migrator Secret 값: 아직 입력하지 않음
- Schema migration: 아직 실행하지 않음

DB 실행 경로를 apply하면 custom migrator Secret 1개의 월 고정 요금과 DB image 저장량이 추가됩니다.
bootstrap·migrate·verify Fargate task는 수동 실행 시간에만 과금되고, 정상 완료 후 상시 실행되지
않습니다. task 실패 시 반복 실행 전에 원인과 DB 상태를 먼저 확인합니다.

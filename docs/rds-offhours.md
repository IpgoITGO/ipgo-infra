# RDS 업무 외 중지 실행기

구현 상태: 로컬 구현·검증 완료, 미배포. 기존 EC2/NAS 예약·RDS·앱·LLM 설정을 변경하지 않는다.
새 Terraform root는 `terraform/environments/rds-offhours`이며 기존 dev state와 분리한다.
기본 `create_resources=false`로 자원 0개다. `apply_approved`, `schedules_enabled`, `stop_enabled`도 모두 false다.
이번 구현 요청은 실제 적용·DB 로그인 role 등록·이미지 push·예약 활성화 승인이 아니다.

## 실행과 상태 보존

Scheduler → dispatcher Lambda → Standard Step Functions → controller Lambda 경로다.
NAS/OAuth는 DB 기동의 필수 경로가 아니다. 기존 예약 ARN은 읽기 대조만 하고 UpdateSchedule 권한을 주지 않는다.
네 새 일정은 KST 매일00:00/04:00, 평일07:00, 토요일22:00이며 모두 기본 DISABLED다.
04:30부터 새 Stop을 금지하고, 자동 Stop은 11/10 이후·11/30 이전으로 제한한다.
07시 기동은 available까지 읽기 대기하고09시에 SQL 감사,09:30까지 미완료면 실패로 남긴다.
08:30에도 available이 아니면 기존 승인 대상 SNS topic에 정형 경고를 한 번 요청한다.
SNS 접수/경보와 사용자에게 실제 알림이 표시됨은 별도이며, 현재 어떤 메시지도 전송하지 않았다.
00시/토요일22시 기동 완료는 `available_sql_not_tested`로 기록해 SQL 성공과 구분한다.

실행 키는 고정 DB ARN·KST 날짜·슬롯·revision의 SHA256이다. 같은 날00시/07시를 합치지 않는다.
dispatcher는 target/SQL/proof override를 받지 않고 예정시각90초 이내만 접수한다.
Standard 실행 이름으로 중복을 제거하고, 원장 락을 획득한 뒤 최신 상태를 다시 읽는다.
Start/Stop intent를 DynamoDB에 먼저 영속화한다. SDK와 workflow의 쓰기 재시도는 없다.
응답 유실/기동 지연 시 상태만 읽고, 최초 FAILED를 후속 성공으로 고치지 않는다.
날짜별 Stop claim과 STOP_BLOCKED 부재 확인을 DynamoDB transaction으로 묶어 revision 간 중복도 차단한다.
테이블은 암호화·PITR·삭제 보호·prevent_destroy를 사용하며 자동 TTL로 실패 원장을 지우지 않는다.

## 중지 게이트와 실제 감사 연결

완료 원문은 `scripts/prepare-rds-prerequisites.py`로 읽는다. 출력은 업로드하지 않는 비공개 검토 요약이다.
관측 status=complete·credited_seconds>=86400·issues 없음·LLM false가 필요하다.
야간 hold/resume의 passed 상태와 verification, cleanup의 자원 부재/STOPPED/INACTIVE·원문 지문을 함께 묶는다.
원래 야간 runner의 세부 검증과 출처 검토를 생략할 수 없으며, 문서/파일 존재만으로 통과시키지 않는다.
출력 자체는 항상 apply_approved=false, stop_enabled=false다. 아직 관측/야간 미완료면 해당 플래그는 false다.

적용 단계에서 요약과 다음 증거를 포함한 최종 manifest를 검토·고정해야 한다.

- schema/revision/DB ARN, 유효 시작·종료 시각, 원문 SHA256 목록.
- `prerequisites`: 안정성 완료/누적 초·야간/정리·DB 사용자/내부 작업 확인·회복 시험·다음 업무일 앱 복구·관리형 start 실검증.
- `db_configuration`: 코드의 `EXPECTED_DB_CONFIGURATION` 전체. 엔진16.15, 암호화·삭제 보호·보존7일·기존 백업/유지보수 창을 모두 비교한다.
- `service_definitions`: 고정 Server/AI task definition의 containerDefinitions digest. config의 정확한 TD ARN 목록 외 revision은 읽지 않는다.
- `existing_schedules`: 실제 name/group/State·식·시간대·Target digest2개. default 그룹으로 추정하지 않는다.
- 읽기 전용 role로 산출한 `schema_sha256`, 고정 DONE run의 `reference_sha256`, 검토한 과거 실패 execution ARN 목록.

manifest는 기존 versioned S3 bucket의 정확한 key/VersionId/SHA256으로 고정한다. 빈 설정·원문 누락·기간 만료는 거부한다.
실행 때 RDS 설정·당일 자동 backup snapshot available/PITR 시각·pending maintenance, EC2 writer host 전체 stopped,
ECS의 다른 running/pending writer와 TD 소스·LLM 명시적 false/키 부재·기존 예약 binding을 실제 읽는다.
현재 실행 이름까지 대조해 다른 workflow나 미검토 실패 이력이 있으면 중지하지 않는다. 과거 실패 이력은 삭제하지 않는다.
manifest의 서비스/기존 예약 목록은 배포 설정의 전체 대상 집합과 대조해 일부 누락·예약 중복을 거부한다.

감사는 독립 Fargate task 1개이며 고정 이미지 digest·기존 subnet/SG를 전달한다. 공인 IP/NAT/EC2/상시 서비스는 만들지 않는다.
AUDIT_KEY 외 command/SQL/role override는 전달하지 않는다. read-only root filesystem·비특권 uid·자체110초 종료 상한을 둔다.
기동부터120초 안에 종료하지 못하거나 감사 도중 중지 게이트가 바뀌면 자기 TD/startedBy/group/key가 맞는 감사 task만 정리한다.
정리 intent를 먼저 저장해 StopTask를 재전송하지 않고 실제 STOPPED를 확인한다. 추가180초에도 불명확하면
최초 skip/failure 사유를 원장에 보존하며 cleanup_unverified 실패와 후속 중지 차단을 남긴다.
일별 최대2회이며 launch 응답 불명도 budget에서 차감한다. 재시도로 추가 task를 띄우지 않는다.

`audit.py`는 별도 Secret의 username=ipgo_rds_auditor를 확인하고 공식 RDS CA로 verify-full 접속한다.
default_transaction_read_only와 실제 READ ONLY/TLS를 확인한 고정 SELECT만 실행한다.
Flyway/열 구조, PENDING/SENT engine job, 다른 client의 열린 transaction, 고정 run/결과/시나리오/설명 digest,
전역 설명 NONE/DISABLED 위반을 읽는다. DB 행·비밀번호·SQL query text는 결과/로그에 담지 않는다.
감사 연결을 닫은 뒤 S3 결과를 If-None-Match:*로 최초 저장한다. 자기 task의 STOPPED/exit0/imageDigest와 key/DB/시각/해시/정수0을 대조한다.
그 뒤 네 큐와 DLQ의 visible/inflight/delayed0을60초 간격으로2회 확인한다.
감사 종료 후 실제 CloudWatch DB connection의 신선한 최대값0이 필요하다. 지표 없음·NaN·오래된 값은0이 아니다.
중지 직전 실제 시계를 다시 읽어04:30/증거 만료를 재검사한다. 조건 누락 시 SKIPPED로 DB를 계속 켠다.

## 권한과 실패 복구

역할은 dispatcher(StartExecution만), workflow(controller Invoke만), controller, audit 실행 역할,
audit task 역할, 실패 guard, Scheduler로 분리한다.
controller의 Start/Stop은 같은 DB ARN1개, RunTask는 정확한 감사 TD, PassRole은 감사 역할2개로 제한한다.
StopTask는 같은 cluster의 Controller 태그와 코드상 소유권 검사를 모두 요구한다.
목록 API와 DescribeTaskDefinition의 Resource:*는 AWS 미지원 제약에 한정하고 리전/cluster와 고정 코드 입력을 적용한다.
DB 삭제/복구·Secret 변경·IAM 변경·앱 UpdateService·기존 Scheduler 변경·업무 큐 송수신·기존 조회 역할 확장은 없다.
감사 role은 Secret1개 Get, 필요 시 그 Secret의 KMS Decrypt, 전용 결과 prefix Put만 가진다.
ECR pull/기존 감사 log group 쓰기는 execution role에만 둔다. 새 log group은 controller 전용14일 보존이다.

DB 권한 정의는 `runtime/rds_offhours/audit-role.sql`이다. 새 NOLOGIN role과 제한된 SELECT만 정의한다.
다른 세션의 transaction은 검색 경로를 고정한 SECURITY DEFINER 집계 함수로만 노출한다.
적용 담당자는 함수 소유자의 통계 가시성을 실측해야 한다. pg_read_all_stats를 auditor에 직접 주지 않는다.
실제 DB 로그인 허용·별도 Secret 생성/회전과 SQL 적용은 미실행이며 별도 승인 범위다. 앱 Secret을 재사용하지 않는다.

모든 실패는 STOP_BLOCKED를 남긴다. workflow 자체 FAILED/TIMED_OUT/ABORTED도 EventBridge guard로 차단하고
CloudWatch native 경보를 기존 승인 대상 SNS topic에 연결한다. guard 지연 시에도 미검토 실패 이력으로 중지를 차단한다.
start 경로는 stop 스위치/차단 원장과 무관하게 유지한다. 자동 차단 해제·실패 원장 덮어쓰기는 없다.
운영 복구 시 새 stop 일정만 먼저 비활성화한다. 기존 EC2 기동·중지2개 예약이나 NAS timer를 변경하지 않는다.
인증된 운영자가 같은 dispatcher에 recovery 슬롯·현재 분 단위 시각을 전달하면 같은 DB를 기동하고 즉시 읽기 감사를 한다.
recovery는 신규 예약이 아니며 당일1회 키로 중복을 막고 후속 stop을 차단한다. 승인 전에는 실행하지 않는다.
stopped만 start, available은 중복 start 없이 감사, stopping/starting은 읽기 대기다.
available/SQL/기존 앱·API/큐 회복을 확인한 뒤 원래 DB 상시 가동으로 되돌리고, 새 start 일정은 마지막에 정리한다.
삭제·재생성·snapshot restore·endpoint/Secret 교체는 이 복구 경로에 포함하지 않는다.

## 검증과 적용 전 잔여

```sh
python3 -m venv .venv-rds
.venv-rds/bin/pip install -r runtime/rds_offhours/requirements.txt
python3 -m unittest discover -s tests/rds_offhours -p 'test_*.py'
.venv-rds/bin/python tests/rds_offhours/verify_aws_contract.py
.venv-rds/bin/python tests/rds_offhours/verify_postgres_tls.py
terraform fmt -check -recursive
terraform -chdir=terraform/environments/rds-offhours init -backend=false
terraform -chdir=terraform/environments/rds-offhours validate
terraform -chdir=terraform/environments/rds-offhours test
terraform -chdir=terraform/modules/rds-offhours init -backend=false
terraform -chdir=terraform/modules/rds-offhours test
```

Terraform test의 mock-provider apply는 메모리 안에서 mock 값으로 평가하며 실제 AWS apply가 아니다.
단위/Stubber는 상태 전이와 API 구조, 로컬 PostgreSQL16 TLS 시험은 실제 고정 SQL·권한·인증서 거부를 검증한다.
CI에 같은 검사를 추가했지만 push 전이므로 GitHub CI 성공으로 보고하지 않는다.
독립 RDS root 변경은 모의 plan·실제 로컬 zip/DB 검사로 검증하며 기존 dev 전체 AWS refresh plan의 대상이 아니다.
CI scope는 기존 dev/공용 모듈/bootstrap 변경과 수동 전체 plan을 유지하고 독립 root만 분리한다.
최초 PR의 전체 dev plan은 기존 역할의 SNS:GetTopicAttributes·budgets:ViewBudget 부족으로 실패했다.
이번 PR에서 권한은 확대하지 않았다. 이후 독립 root 검증 통과나 dev plan 비대상 판정이 그 권한 문제의 해결을 뜻하지 않는다.
공식 CA와 SHA256으로 고정한 Python base image로 로컬 감사 이미지를 빌드한다. ECR push/운영 digest 등록은 하지 않는다.

실제 네트워크 경로·서비스 역할/DB 권한·Fargate 기동 시간·cold start/회복 시간·알림 전달·비용은 미실측이다.
관측/야간 완료 후에만 계정/리전·기존 자원·감사 네트워크/endpoint/ECR/Secret/S3/logging을 재검증한다.
pilot/app 복구 증거를 추가하고 immutable manifest·이미지 digest를 고정한 뒤, 새 자원만 포함한 plan/비용/복구를 승인받는다.
현재 dev apply workflow는 기존 dev root 전용이므로 새 root의 OIDC 적용 경로와 역할 범위도 그 단계에서 별도 검토한다.
실제 apply/DB role/이미지 push/Stop은 아직 허용하지 않는다.11월 말 stop 금지와 전체 신규 예약의 월 한정도 유지한다.
제어 비용0.50USD는 이전 계획의 여유 가정이며 이번 로컬 시험으로 실청구 검증한 값이 아니다.
원장 PITR/로그·workflow·Fargate·SNS의 실제 단가와 건수를 최종 plan에 반영해50USD 한도에 재대조한다.

근거: [Standard 실행의 중복 처리](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html),
[ECS API](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_RunTask.html),
[ECS IAM 자원 제한](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ecs.html),
[RDS TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).

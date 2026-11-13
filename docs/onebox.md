# 개발 서버 단일 호스트 운영

개발 API 주소는 `https://ipgo-dev-api.iwhya.kr`이다. 프론트의 API 주소와 로그인 방법은 유지한다.
DB는 기존 private RDS를 사용하며 데이터, DB 역할, JWT 키, S3와 큐를 옮기거나 초기화하지 않는다.

## 현재 요약 — 2026-11-13 12:46 KST 관측

- Infra #63에서 공식 AWS NAS 읽기 MCP로 계정·서울 리전과 Server/AI 서비스·실행 태스크·태스크 정의를 확인했다.
  Server TD46/`1b3be78`과 AI TD22/`8a7e970`은 같은 container instance에서 각각 목표 1·실행 1·대기 0이며,
  두 앱 컨테이너의 자체 health check 상태는 `HEALTHY`였다. 외부 HTTP·실제 업무 흐름은 이번에 시험하지 않았다.
- Server 정책은 아래 계약과 이미 일치하여 AWS 변경·배포·재기동 없이 선행 읽기 확인을 마쳤다.
  Secret 값·IAM 정책·호스트 여유 자원과 실제 LLM 동작은 미조회다. 기존 AI 정책 및 적용 승인 범위는 유지한다.
- 다음은 Infra 문서 검토 후 Server #209의 정책 사전 검사·자동 설정 제거다. 실제 배포 검증은 별도 승인 후 수행한다.

## 이전 관측 — 2026-11-13 11:00 KST

- 공식 AWS NAS 읽기 MCP로 계정·서울 리전을 확인하고 ECS 서비스·실행 태스크·태스크 정의를 조회했다.
  AI TD21/`8a7e970`과 Server TD46/`1b3be78`은 같은 호스트에서 각각 목표 1·실행 1·대기 0이며,
  두 앱 컨테이너의 자체 health check 상태는 `HEALTHY`였다.
- AI는 `real`, 내장 worker 활성, 독립 worker 0개다. 지속 LLM 활성 설정과 키 참조도 존재하지만
  이번 조회는 실제 LLM 응답·품질·청구나 사용자 업무 성공을 검증하지 않았다.
- AI 배포 정책은 이미 `0/100`으로 일치했다. 이번 문서화에는 AWS 설정 변경·재기동·배포가 없다.
  아래 날짜가 있는 이전 배포·시험 기록은 당시 결과이며 현재 관측과 구분한다.

## 구성과 비용

CloudFront가 HTTPS를 처리하고 private VPC origin으로 앱에 연결한다. API 응답은 캐시하지 않으며
Authorization, 쿠키, 요청 헤더와 쿼리 문자열을 전달한다. HTTPS 리다이렉트와 기존 인증서 검증용
CNAME을 유지한다. 인증서는 ACM이 갱신하므로 호스트에 인증서 개인키나 별도 인증서 갱신기를 두지 않는다.

앱과 AI는 같은 ARM EC2에서 별도 ECS EC2 태스크로 실행한다. 각 태스크는 기존의 서로 다른 IAM 역할을
사용한다. 호스트는 IMDSv2를 요구하며 앱 포트는 기존 ALB와 AWS가 관리하는 CloudFront VPC origin SG만 허용한다.
서버의 S3 쓰기 권한과 AI의 조회 권한을 하나의 공용 자격증명으로 합치지 않는다.

| 항목 | 개발 설정 |
| --- | --- |
| 호스트 | 서울 t4g.micro, ARM64, 1GiB, encrypted gp3 30GiB |
| CPU 과금 | Standard credit, 상세 모니터링 꺼짐 |
| 앱 | `ipgo-dev-onebox-server`, bridge 8080, 메모리 448MiB |
| JVM | heap 128MiB, SerialGC, Tomcat 최대 16 threads, DB pool 최대 3 |
| AI | `ipgo-dev-onebox-ai-api`, bridge 8000 → host 18000, 메모리 256MiB |
| AI 모드 (2026-11-13 관측) | real, 내장 worker 활성·독립 worker 0; LLM 응답·업무 검증과 구분 |
| DB | 기존 RDS, private 접근·7일 백업·삭제 보호 유지 |
| 관측 | ECS container insights 꺼짐, 표준 EC2 지표, 5분 간격 메모리 지표 |
| 장애 확인 | 2분 간격 실제 HTTPS health와 OpenAPI, 실패/누락 4분 경보, CloudFront 5xx 비율 경보 |

아래는 최초 전환 때의 31일·744시간 기준 예상 비용이며 이번 조회에서 가격·실제 청구를 갱신하지 않았다.
무료 크레딧과 장기 약정은 가정하지 않는다.

| 항목 | USD, 세전 월 환산 |
| --- | ---: |
| EC2 | 7.74 |
| EC2 디스크 30GiB | 2.74 |
| public IPv4 1개 | 3.72 |
| 기존 RDS와 20GiB 디스크 | 21.22 |
| 기존 Secret 6개 | 2.40 |
| 기존 private DNS 영역 | 0.50 |
| 표준 경보 7개·custom metric 3개 | 1.60 |
| ECR·로그·저용량 CloudFront·기타 사용량 가정 | 약 1.30 |
| 합계 | 약 41.22 |

한국 VAT 10%를 가정하면 **약 45.34 USD**, 월 50 USD 대비 약 4.66 USD의 여유다.
CloudFront·로그·트래픽·추가 백업/스토리지 등의 실제 사용량에 따라 달라진다. 기타 사용량에는 지표 조회/등록 API의 소액 여유도 포함한다. 이미 발생한 기존 환경 비용과
이전 중 병행 비용은 별도이며, 이 표는 전환 이후의 운영비 환산이다. 외부 LLM 청구도 포함하지 않는다.
기존 월 50 USD 예산과 실제 40/50 USD·예상 50 USD 알림은 유지한다. 예산 알림은 자동 과금 차단 장치가 아니다.

## 공유 호스트 AI 배포 정책

관련 작업은 [Infra #61](https://github.com/IpgoITGO/ipgo-infra/issues/61)과
[AI #105](https://github.com/IpgoITGO/ipgo-ai/issues/105)다. 정책의 정본은 이 절이며,
범위는 개발 환경의 onebox AI 서비스다. 기존 Fargate 서비스와 Server workflow는 이번 변경 대상이 아니다.

### 정책과 실제 설정

2026-11-13 10:59~11:01 KST의 `DescribeServices`, `DescribeTasks`, `DescribeTaskDefinition` 조회 결과다.
관측값은 이후 배포·쓰기 직전의 fresh 확인을 대신하지 않는다.

| 항목 | 정책·관측값 |
| --- | --- |
| 배포 방식 | EC2, ECS controller, `ROLLING` |
| 배포 비율 | `minimumHealthyPercent=0`, `maximumPercent=100` |
| 실패 복구 | deployment circuit breaker와 rollback 활성 |
| health 유예 | `healthCheckGracePeriodSeconds=300` |
| AI 실행 기반 | ARM64, 메모리 256MiB, `bridge`, container 8000 → 고정 host 18000 |
| AI 수량 | 정상 운영 목표·실행 1, 대기 0; 승인된 API 수량은 최대 1 |
| worker | 내장 worker 활성, 독립 worker 서비스 목표·실행·대기 0 |
| 공유 상태 | Server와 같은 container instance; Server 메모리 448MiB·고정 host 8080 |

하나의 호스트에서 같은 고정 포트를 사용하는 두 AI 태스크를 동시에 배치할 수 없다.
목표 1개에서 `0/100`은 기존 태스크를 먼저 내리고 새 태스크를 시작할 수 있게 하므로,
AI 재배포에는 일시 중단이 있다. 무중단 배포로 안내하지 않으며 `maintenance_approved`를 유지한다.
비율의 의미는 [AWS의 ECS 태스크 교체 설명](https://aws.amazon.com/blogs/containers/a-deep-dive-into-amazon-ecs-task-health-and-task-replacement/)을 따른다.
서비스를 0으로 내리는 작업도 별도 승인 범위이며, real 모드의 수량·내장 worker·용량 승인 검사는 AI에 남긴다.

### 관리 책임과 AI 검증 계약

- Infra는 배포 정책의 결정·변경·독립 검증·복구와 이 문서를 관리한다. onebox ECS 서비스는
  아래에 적힌 기존 공식 AWS MCP 관리 경로를 유지하며, 이번에 Terraform으로 일괄 이전하지 않는다.
- AI는 이미지 빌드·digest 검증·배포, 승인 범위 내 태스크 수 반영, 앱 검증을 맡는다.
  사전 검사와 최초 ECS 쓰기 직전에 대상 계정·리전·서비스와 위 배포 정책의 일치를 확인한다.
- AI #105에서 확인할 핵심은 ECS controller·ROLLING·`0/100`·circuit breaker/rollback 활성이다.
  EC2·ARM64·메모리·고정 포트·worker 수량은 공유 호스트 제약으로 함께 대조한다.
  누락·조회 실패·불일치 시 쓰기 전에 중단하며 AI workflow가 정책을 자동 보정하지 않는다.
- 승인 SHA, maintenance·capacity·LLM 승인과 기존 이미지·active template·rollout·앱 health 검사를 유지한다.
  Secret·IAM·메모리·Server 설정을 정책 분리 명목으로 변경하지 않는다.

현재 AI workflow는 배포마다 `Configure approved one-box restart`에서 `0/100`을 설정한다.
이 문서만으로 실행 경로가 바뀐 것은 아니다. 해당 명령 제거와 사전 검증 구현은 AI #105의 후속 범위다.

### 적용 순서와 완료 판단

1. Infra #61에서 이 정책 계약·실제 관측·중단 영향·복구 절차를 검토하고 문서 PR을 `dev`에 반영한다.
2. AI 전환 직전에 실제 정책을 다시 읽는다. 일치하면 AWS 쓰기 없이 선행 조건을 충족한다.
   불일치하면 동시 작업·드리프트 원인을 확인하고 대상·영향·검증·복구를 구체화해 별도 승인받는다.
   중요한 설정을 변경하기 전에는 기존 HDD 복구 스냅샷 절차를 통과해야 한다.
3. AI #105에서 검증을 먼저 추가하고 정책 변경 명령을 제거한다. 정책 일치·불일치·누락·조회 실패와
   legacy 경로의 회귀검사 및 필수 CI를 확인한다. Infra 근거를 연결한 뒤 `dev`에 병합한다.
4. 정확한 SHA·환경·영향을 승인받은 다음 AI 배포에서 실제 task definition·image digest·rollout·앱 health,
   정책 유지와 Server 영향을 확인한다. 문서 반영·CI 통과·배포 성공·실제 업무 성공은 각각 구분한다.

### 검증 한계와 복구

이번에는 서비스 5개와 실행 태스크 2개의 목록·상세를 확인했으며 목록의 미조회 후속 페이지와 실패 항목은 없었다.
두 태스크의 container instance 식별자가 같아 공유 호스트임을 확인했다. 다만 NAS 읽기 역할의
`ListContainerInstances`·`DescribeContainerInstances`는 권한 거절로 조회하지 못했다.
호스트 잔여 CPU·메모리, EC2 상세, 최대 입력·장기 부하와 실제 사용자 흐름은 이번 검증 범위가 아니다.
앱 `HEALTHY`는 태스크 정의의 HTTP health check 결과이며 별도의 사용자 업무·외부 HTTP 시험을 수행한 것은 아니다.
Secret 값은 조회하지 않았다. 계정 ID·ARN·내부 주소·원본 응답은 공개 문서에 추가하지 않는다.

현재는 AWS 정책이 일치하고 실제 변경이 없어 운영 rollback 대상이 없다.
향후 이미지 복구는 AI, 정책 복구는 Infra가 사전 관측한 호환 설정을 기준으로 승인 범위를 확인해 수행한다.
정책 변경 시에는 승인된 필드만 바꾸고 기존 circuit breaker 등 나머지 설정을 보존한 뒤 독립 조회한다.
AI 코드 revert는 제거했던 정책 변경 명령을 되살릴 수 있으므로 정책 소유권·호환성을 확인한다.
정상 이미지 복구 시에도 현재 승인된 설정·업무 처리 상태를 보존하고, 중복 처리 가능성을 확인한다.
queue purge·업무 데이터 삭제·DB 전체 복원을 기본 복구 수단으로 사용하지 않는다.

## 공유 호스트 Server 배포 정책

관련 작업은 [Infra #63](https://github.com/IpgoITGO/ipgo-infra/issues/63)과
[Server #209](https://github.com/IpgoITGO/ipgo-server/issues/209)다. 이 절은 개발 onebox Server의 정책 정본이다.
AI #61 계약과 legacy Fargate 서비스 정책은 별도이며, 기존 코드를 일괄 이전하지 않는다.

### 정책과 실제 확인

2026-11-13 12:46 KST 공식 AWS NAS 읽기 MCP의 계정·서울 리전 확인 후 `DescribeServices`,
`ListTasks`, `DescribeTasks`, `DescribeTaskDefinition`으로 아래 값을 확인했다. API 실패·후속 페이지는 없었다.

| 항목 | 정책·관측값 |
| --- | --- |
| 실행 방식 | EC2, `REPLICA`, ECS controller, `ROLLING` |
| 배포 비율 | `minimumHealthyPercent=0`, `maximumPercent=100` |
| 실패 복구 | deployment circuit breaker의 enable·rollback 모두 활성 |
| AZ 재균형 | `availabilityZoneRebalancing=DISABLED` |
| Server 실행 기반(관측) | ARM64/Linux, `bridge`, 메모리 448MiB, container/고정 host 8080 |
| 수량(관측) | 목표 1·실행 1·대기 0; 배포 입력은 기존 승인 범위 0 또는 1 유지 |
| 공유 상태(관측) | AI TD22와 같은 container instance; 두 앱 자체 health check `HEALTHY` |

단일 호스트에서 고정 포트 8080을 쓰는 두 Server 태스크를 동시에 배치할 수 없다.
`0/100`은 기존 태스크를 내린 뒤 새 태스크를 시작할 수 있게 하므로 재배포에는 일시 중단이 있다.
기존 `maintenance_approved`와 승인한 수량·SHA·영향 확인을 유지한다.

### 관리 책임과 Server 검사 계약

- Infra가 정책 결정·변경·독립 검증·복구와 이 절을 관리한다. 기존 공식 AWS MCP 관리 경로를 유지하고,
  onebox 서비스를 Terraform으로 일괄 이전하지 않는다. Terraform compute의 Fargate `100/200`과 혼동하지 않는다.
- Server는 이미지·태스크 정의 배포, 승인 범위 내 수량 반영, rollout·앱 검증을 담당한다.
  사전 검사와 기존 active template 확인을 사용하는 최초 ECS 쓰기 직전에 위 표의 실행 방식·비율·실패 복구·AZ 재균형을 읽어 대조한다.
  누락·조회 실패·불일치 시 쓰기 전에 중단한다. workflow는 배포 정책을 자동 설정·복구하지 않는다.
- 수량·메모리·포트·이미지·Secret 참조·IAM은 이번 정책 분리로 변경하지 않는다. 실행 기반과 수량은 관측 근거이며,
  이 작업이 별도 capacity 승인이나 호스트 자원 검사를 대신하지 않는다. 기존 이미지·템플릿·rollout·앱 검사도 유지한다.
- 배포 후 같은 정책을 다시 검사하고 실패하면 배포 성공으로 처리하지 않는다. AI 동작·공유 호스트 영향은 별도로 확인한다.

### 적용 순서·검증 한계·복구

1. Infra #63 정책 문서를 검토하고 실제 일치 근거를 Server #209에 연결한다. 이번 확인에서는 AWS 쓰기가 필요 없었다.
2. Server #209에서 사전/쓰기 직전/배포 후 검사와 회귀검사를 추가하고 정책 설정 단계를 제거한다.
   문서와 실제 일치 근거 확인 후 병합·적용하며, 과거 관측을 쓰기 직전 fresh 확인으로 재사용하지 않는다.
3. 정확한 SHA·환경·일시 중단 영향·검증·복구를 별도 승인받은 실제 배포에서 rollout·앱 health·정책 유지·AI 영향을 확인한다.
   코드·CI·실제 배포·사용자 업무 성공을 각각 구분한다.

이번에는 Server와 AI 2개 서비스와 실행 태스크 2개를 확인했다. 호스트 상세·잔여 CPU/메모리·장기 부하·외부 HTTP·
사용자 업무·Secret 값·IAM 정책은 검사하지 않았다. AI TD22는 이번 관측값이며 이전 TD21 관측을 불변으로 보고하지 않는다.
계정 ID·ARN·내부 주소·원본 응답은 공개 문서에 추가하지 않는다.

AWS 변경이 없으므로 이번 운영 rollback 대상은 없다. 향후 정상 이미지 복구는 Server, 정책 복구는 Infra가 맡는다.
정책 불일치 시 동시 변경·관리 경로를 확인하고, 승인한 필드만 변경하며 나머지 설정을 보존한다.
중요 설정 변경 전 HDD 복구 스냅샷과 별도 승인을 확인하고 변경 뒤 독립 조회한다.
Server 코드 revert가 정책 설정 명령을 되살릴 수 있으므로 소유권·호환성을 확인한다.
업무 데이터 삭제·queue purge·DB 전체 복원을 기본 복구 수단으로 사용하지 않는다.

## 최초 이전 당시 코드와 검증 범위 (과거 기록)

이전 대상은 현재 배포 중이던 앱 `cdf98be9a248fe9b2f24a5cdbe6d83267a9c49a9`와
AI `40b301a3c9fa3231f813f73deacb9d7dbc7df977`이다. 최신 dev 기능 배포와 분리한다.
ARM 이미지는 `<source SHA>-arm64` 태그로 보관하고 실제 태스크는 digest로 고정한다.

1GiB 첫 시도는 앱 메모리 384MiB 제한으로 OOM이 발생했다. 기존 서버에는 영향을 주지 않았다.
JVM heap 128MiB와 thread/connection 수를 조정하고 앱 제한을 448MiB로 설정한 뒤 다음을 확인했다.

- 격리 PostgreSQL에서 로그인·갱신·로그아웃·Swagger·AI mock 등 25개 검사, 340개 요청 통과
- 파일당 약 9.94MiB 업로드 6건(3건 동시 포함), 인증 조회 480건 통과
- CPU Standard 설정에서 동일 25개 검사와 340개 요청 통과
- 통과한 실행의 앱/AI OOM kill과 재시작 0
- 실제 RDS를 사용하는 새 서버에서 기존 JWT·쿠키를 수용하고, 새 토큰도 기존 서버에서 수용함
- 기존/새 서버 사이의 로그아웃 세션 폐기, HTTPS 인증서·Swagger·보호 API 검사 28개 통과
- 실제 태스크별 IAM 역할 분리·S3 읽기 전용 확인·앱→AI health와 AI의 RDS verify-full/조회 전용 연결 확인

대용량 실계산, 최대 상품 수, 장기간 부하와 브라우저 전체 업무 흐름을 모두 검증한 결과는 아니다.
이전 당시의 AI 업무 연동 미구현과 SMTP 미설정 등 제한도 최초 이전 작업에서 해결한 것으로 표현하지 않는다.
새 기능이나 real/worker를 배포하기 전에 해당 코드의 메모리·부하를 재검증한다.

## 배포와 관리 주체

- 기존 VPC·RDS·IAM·S3·큐·예산·SNS와 기존 서비스 메타데이터: Terraform
- 새 호스트와 CloudFront ingress: `cloudformation/onebox-host.json`
- 새 장애 확인 함수와 경보: `cloudformation/onebox-monitoring.json`
- CloudFront VPC origin·distribution와 새 ECS 서비스/태스크: 공식 AWS MCP로 관리, 실제 식별자는 비공개 운영 기록에 보관
- 메모리 수집: `scripts/onebox/`의 Python·systemd 파일. 이미 검증한 ARM AI 이미지를 별도 local tag로 고정해 실행

호스트 stack은 검증용 stack을 영구 호스트로 전환한 것이다. 3시간 종료 예약을 취소했고
guest shutdown은 stop, EC2와 stack의 삭제 보호를 켰다. 임시 이미지 push 권한과 호스트의 DB secret 조회 권한은 제거했다.
태스크 실행 역할의 기존 Secret 조회 권한은 유지한다.

호스트를 새로 구성할 때는 기존 subnet/server SG, 검증할 ECS ARM AMI, cluster와 CloudFront managed SG를 입력한다.
기존 RDS를 새로 만들거나 DB bootstrap/migrate를 실행하지 않는다. 호스트 IAM 역할로 ECS agent를 등록하고
`ipgo.onebox=true` attribute를 확인한다. 기존 container instance를 재사용할 때는 `PutAttributes`로 명시한다.
앱/AI의 기존 task role·execution role·secret 참조를 유지하면서 새 host IP에 맞는 AI URL과 포트를 확인한다.

메모리 수집 이미지는 승인한 ARM digest를 `ipgo-onebox-memory-monitor:local`로 tag한다. 이미지의 앱 진입점 대신
`report-memory.py`만 실행하며 host network로 IMDSv2의 호스트 역할을 사용한다. 80MiB 메모리 제한,
낮은 CPU 우선순위와 높은 OOM 종료 우선순위로 앱을 보호한다. 별도 상주 모니터링 agent는 설치하지 않는다.
서비스와 timer를 설치한 뒤 실제 `MemoryAvailablePercent` 수신까지 확인한다.

Server/AI GitHub 변수 `AWS_DEV_COMPUTE_MODE=onebox`는 ARM runner와 새 ECS 서비스를 선택한다.
기존 task definition의 메모리·IAM·DB 설정을 이어받고 이미지부터 바꾼다. AI API는 최대 1개, 독립 worker 서비스는 0개로 유지한다. real 모드의 worker는 API 프로세스 안에서 한 개만 실행한다.
한 호스트에서 같은 포트를 쓰므로 이후 코드 배포에는 짧은 서비스 재시작이 필요하다.
배포 workflow는 검토 후 `maintenance_approved`를 선택해야 진행한다. 최초 이전 당시에는 기존 서버를 병행해 연결을 넘겼다.

## 연결 전환과 복구

1. 기존 ALB·서버를 유지한 채 새 앱과 AI의 실제 health, DB·IAM·S3·인증을 확인한다.
2. 새 호스트 private IP:8080을 기존 ALB target group에도 등록하고 `healthy`를 확인한다.
3. 기존 Fargate server/AI를 0으로 줄인다. ALB와 CloudFront 양쪽은 같은 새 서버로 연결한다.
4. 호스팅케이알의 API CNAME을 검증한 CloudFront 주소로 바꾼다. 기존 ACM 검증 CNAME은 유지한다.
5. 권한 있는 DNS·복수 공개 resolver·실제 HTTPS와 로그인, 기존 ALB의 요청 감소를 확인한다.
6. DNS 캐시와 기존 연결이 배출된 뒤 ALB를 제거하고 `AWS_ENABLE_LEGACY_ALB=false`를 유지한다.
   Terraform의 기존 ALB 관련 resource는 conditional count와 moved block으로 보존/제거를 구분한다.
   기존 ALB/ECS 경보만 제거하며 RDS 경보·예산·SNS 구독을 유지한다.

ALB가 남아 있는 전환 중에는 기존 Fargate를 원래 task definition으로 1개씩 복구하고 ALB health를 확인한다.
새 target을 제거하는 것은 기존 target이 healthy가 된 뒤에만 한다. DNS를 원래 ALB로 돌려도 DB와 JWT는 같다.
ALB 제거 후 호스트 장애는 ECS/EC2 복구 또는 새 호스트 검증 → CloudFront origin 갱신으로 대응한다.
기존 ALB 재구성이 필요하면 비용과 plan을 검토하고 legacy 설정으로 복원한다.
한 호스트 운영은 이중화 구성이 아니며, 장애 복구와 이후 재배포의 재시작 시간을 별도로 고려한다.

DB 전체 복원이나 회원/업로드 삭제를 서버 이전의 기본 롤백 방법으로 사용하지 않는다.
배포 전후 서비스 수량, task/image digest, 실제 HTTPS·로그인 결과, DB 백업/보호, 경보·예산 상태와
복구 입력은 비공개 운영 기록과 통합 `docs/status.md`에 남긴다. 비밀번호·토큰·계정별 ARN은 공개 문서에 적지 않는다.


## 실제 정제·계산 연결 배포 준비 (IPGO-111 / IPGO-118)

이번 변경안은 기존 개발 주소와 DB를 유지하며 실제 XLSX 정제·계산 결과를 Spring에 저장하는 경로다.
AI API 한 프로세스에 worker thread 한 개를 함께 실행하고 별도 worker 서비스는 0개로 유지한다.
실제 적용 전에는 해당 앱 SHA의 메모리·재시도·동시 처리와 PostgreSQL/SQS 통합 검증이 필요하다.
2026-11-02에 Server PR74와 AI PR52의 검증한 tree를 개발 환경에 적용했다. 아래 준비 절차와 실제 확인 범위는 구분하며, 후속 검증 상태는 연결된 GitHub 이슈를 따른다.

- SQS jobs/results/DLQ 총 4개의 최대 메시지 크기만 256KiB에서 1MiB로 늘린다.
  보관·재시도·권한은 유지하며 Terraform plan에서 4개 in-place 변경만 확인한다.
- AI 결과는 900,000 UTF-8 bytes를 초과하면 작은 실패 결과를 보내며 원문을 잘라 성공으로 표시하지 않는다.
  AI의 S3 쓰기 권한이나 새 저장소는 추가하지 않는다.
- 서버 V14 migration은 작업 outbox, 계산 input hash, 계산 사유의 길이 확장과 조회 전용 view 3개를 추가한다.
  기존 업무 행·원본·JWT는 초기화하지 않으며, 이전 PROCESSING 행을 자동 재처리하지 않는다.
- 일반 코드 적용과 DB schema 적용을 구분한다. 실제 RDS 변경은 snapshot 및 복구 입력을 준비하고
  DB 작업 절차에 따라 서비스 일시 중지·migration·검증·기동을 구체화한 뒤 승인받는다.
- 실제 계산과 유료 LLM은 별개다. `ENGINE_MODE=real`, `IPGO_EMBEDDED_WORKER_ENABLED=true`로
  계산을 실행하더라도 LLM 승인/실제 key 없이 OpenAI를 활성화하지 않는다.
  서버의 `IPGO_ENGINE_ENABLED=true`는 DB/큐 검증을 마친 뒤에만 설정한다.
- 단일 호스트 workflow의 maintenance 승인과 real capacity 승인은 해당 배포의 검사 결과를 확인한 뒤 선택한다.
  컨테이너 실행 수·역할·메모리 제한을 임의 확대하지 않는다.

원복은 먼저 새 서버 발송과 AI embedded worker를 끄고 기존 task revision/mock으로 되돌린다.
추가한 schema는 남겨 기존 데이터 손실을 막으며, 이전 이미지가 새 schema에서 기동하는지 사전 확인한다.
이미 전송된 작업은 DB jobId와 결과 상태를 대조하며 queue purge/DB 전체 복원을 기본 복구로 쓰지 않는다.
큐 크기를 줄일 때는 큰 미처리 메시지가 없는지 확인한다.

AWS의 1MiB 지원은 [공식 발표](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-sqs-max-payload-size-1mib/)와
[FAQ](https://aws.amazon.com/sqs/faqs/)를 따른다. 메시지는 64KiB 요청 단위로 과금되며,
이번 변경은 새 상시 리소스를 추가하지 않는다. 실제 사용량은 기존 월 50달러 예산 알림으로 확인한다.


## 단일 호스트 배포 시 AZ 재조정 설정

단일 호스트 서비스는 `minimumHealthyPercent=0`, `maximumPercent=100`으로 재시작한다.
ECS의 `availabilityZoneRebalancing`이 `ENABLED`이면 maximumPercent 100 이하를 거부하므로,
서비스 생성·복구 시 두 onebox 서비스 모두 **`availabilityZoneRebalancing=DISABLED`**를 명시한다.
기존 서비스는 공식 AWS MCP의 UpdateService로 같은 값을 설정한 뒤 재시작한다.
단일 호스트에 태스크를 두 개씩 올리거나 메모리·포트 제한을 늘려 해결하지 않는다.

2026-11-02 첫 실제 연결 배포는 이 설정 충돌로 GitHub Actions의 서비스 재시작 단계에서 실패했다.
승인된 앱 tree와 빌드된 ARM 이미지 digest를 바꾸지 않고 AZ 재조정만 끈 뒤,
공식 AWS MCP로 새 task definition을 등록·기동했다. 서비스에 이 설정이 유지되면 기존 배포 workflow의
min0/max100 재시작을 사용할 수 있다. 설정 변경과 앱 SHA 승인을 구분하며 최신 dev로 임의 교체하지 않는다.

- 실제 배포 source: Server `011863a804f307ca7a2de50ca95f9cfbd24d66eb`,
  AI `c77e24292c970d2f0f855cb63f474099b52d39df`(engineVersion 0.3.0).
  각각 승인된 PR74 `ba965d7`, PR52 `1b1161d`와 Git tree가 같다.
- V14는 사전 RDS snapshot 후 migrate/verify workflow로 적용했다. 기존 DB bootstrap과 비밀번호 재설정은 실행하지 않았다.
- SQS 4개 최대 크기는 실제 1MiB로 바꿨고, 기존 DB·개발 주소·상시 서버 수·JWT와 역할을 유지했다.
- Server engine 활성화, AI real/embedded worker 1개, 독립 worker 0개이며 유료 LLM은 비활성이다.
- 적용 후 공개 HTTPS·Swagger·보호 API·로그인·갱신·로그아웃 28개 검사가 통과했다.
  적용 전 refresh cookie의 적용 후 갱신도 별도로 확인했다.
- 공개 health 관측에서 실패 시작 22:32:18, 정상 복귀 22:50:34(KST)였다.
  예상 5~10분보다 길어진 약 18분 16초의 점검 중단이며 상시 무중단 구성으로 안내하지 않는다.
- 실 AWS 합성 31상품 정제·계산·저장과 재기동 후 내부 상태를 추가 확인했다.
  아래 최종 검증 범위와 남은 메모리 경보를 따르며 실 고객 데이터 전체 검증으로 확대하지 않는다.


## 메모리 지표의 수집 시점

호스트 여유 메모리는 짧게 실행되는 수집 컨테이너 안에서 읽는다. AWS SDK를 먼저 import하면
SDK의 일시적인 메모리 사용량까지 매번 기본 사용량에 포함된다. 지표는 **SDK 로드 전**에
`/proc/meminfo`를 읽고, 이후 같은 노드 역할로 전송한다. 실제 MemAvailable 값을 보정하거나
10% 경보 기준을 낮추지 않는다. 수집기의 80MiB 제한·낮은 우선순위·5분 주기도 유지한다.
앱·AI 자체 사용량, 업로드·계산 중 메모리와 OOM/재시작은 이 기준 지표와 함께 확인한다.


## 실제 연결 최종 검증과 남은 메모리 안정화 — 2026-11-02

개발 주소와 DB를 유지한 채 승인된 Server PR74 / AI PR52의 ARM 이미지로 실제 연결을 운영한다.
Source SHA는 Server `011863a804f307ca7a2de50ca95f9cfbd24d66eb`,
AI `c77e24292c970d2f0f855cb63f474099b52d39df`(0.3.0)이며 승인 head와 Git tree가 같다.
실제 계산은 활성화됐고 유료 LLM은 비활성이다.

- 실제 AWS의 새 합성 계정에서 31상품 XLSX 2개월을 업로드해 S3/SQS→AI 정제→계산 2회→결과 저장·조회까지 확인했다.
  결과 62행·시나리오 186행, 조건 변경에 따른 권장 수량 25→35와 금액 2500→3500, 소진일·입고 판정·올림 전 값이 기대값과 일치했다.
- 잘못된 파일은 FAILED로 종료되고 이전 성공 결과는 보존됐다. 작업은 DONE4/FAILED1, 네 큐와 DLQ 잔량0이었다.
  검증 자료는 별도 합성 계정에만 추가해 이력으로 남겼고 시험 세션은 폐기했다. 기존 사용자 자료는 초기화하지 않았다.
- RDS verify-full/조회 전용 view·쓰기 금지를 확인했다. DB는 available/7일 백업/삭제 보호, 사전 snapshot도 available이다.
- 양쪽 앱 자체 HEALTHY, OOM kill·재시작0. ARM cgroup peak는 앱401.93MiB/448MiB, AI173.91MiB/256MiB였다.
  각 peak는 다른 시점이며 동시에 합산한 호스트 peak가 아니다.
- 기능 배포는 완료했으나 **호스트 메모리 여유 최신5.86%·메모리 경보1개 ALARM**이 남았다. 나머지6개 경보는 OK다.
  [Infra#31](https://github.com/IpgoITGO/ipgo-infra/issues/31),
  [IPGO-119](https://ehwiya.atlassian.net/browse/IPGO-119)(이휘)에서 별도 안정화한다.
  지표 샘플 시점 개선은 메모리 부족을 해결한 것으로 보고하지 않으며 경보 기준10%를 유지한다.
- 검증기 최종 로그 출력 오류는 별도 읽기 전용 감사15검사/exit0로 저장 상태를 대조했다.
  임시 Fargate 검증 태스크3개는 STOPPED/전용 정의 INACTIVE로 정리했고 상시 서버 수는 늘리지 않았다.

실 고객 CM-01, 최대 입력·장시간 부하, 전체 프론트 브라우저 흐름, 위험·정확도·전체 DA05·유료 LLM·SMTP는 별도 범위다.
현재의 작은 합성 입력 성공을 그 범위의 완료로 확대하지 않는다.

# DA-01 로컬 연동 시험 격리·접근 계약

상태: **계약안 검토 단계 / 환경 미구축·연동 시험 미실행**.
관련 작업: [Infra #68](https://github.com/IpgoITGO/ipgo-infra/issues/68) →
[AI #57](https://github.com/IpgoITGO/ipgo-ai/issues/57).
문서 반영과 실제 격리 구축·연동 성공은 별도로 판단한다.

## 목적과 범위

로컬 Server·AI 시험이 개발 환경의 작업·데이터·worker에 간섭하지 않도록 DB·메시지·원본 저장소와 접근 경계를 정한다.
기본안은 독립 로컬 시험 환경이며 새 RDS·EC2 생성을 전제로 하지 않는다.
기존 공유 호스트 배포 정책과 SQS visibility timeout 정책은 이 계약에서 변경하지 않는다.
이 문서는 코드 수정·환경 구축·AWS 설정 변경·배포·Secret 값 주입·유료 LLM 호출의 승인이 아니다.

## dispatcher 코드 점검 근거

2026-11-13 코드 점검 기준은 Server `55bdc6533c083afa0dee5bbcf5a739f147cb746d`,
AI `b2f685fc852e524a079c20fc5d8d6a7eb2791f37`이다. 실제 접속 구성·간섭 발생 여부는 조회하지 않았다.
같은 작업·업무 테이블에 접근 가능하고 별도 DB 격리 제약이 없다면 다음 경로로 간섭할 수 있다.

| 경로 | 확인한 내용과 영향 |
|---|---|
| [작업 선택·claim](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/service/EngineJobs.java#L47-L66) | 상태·재시도 시각·jobId로 선택하며 환경별 소유권 조건이 없다. lease는 동시 전송 방지용으로 환경을 구분하지 않는다. |
| [발행·만료 처리](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/infrastructure/EngineTransport.java#L46-L55) | claim한 작업을 그 Server의 jobs 큐로 보낸다. 큐를 분리해도 다른 환경 작업을 가져갈 수 있으며, 발행 전 만료 처리도 수행한다. |
| [만료 조회](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/service/EngineJobs.java#L84-L92)·[실패 반영](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/service/EngineResults.java#L69-L83) | 공유 테이블의 오래된 작업을 환경 구분 없이 찾아 업무 결과와 작업 상태를 실패로 바꿀 수 있다. |
| [결과 수신·ACK](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/infrastructure/EngineTransport.java#L57-L62)·[결과 저장](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/service/EngineResults.java#L31-L66) | DB commit 뒤 ACK한다. results 큐를 공유하면 다른 인스턴스가 결과를 반영하거나, 모르는 jobId를 받아 ACK하지 못해 재전달을 지연시킬 수 있다. |
| [업로드 작업 등록](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/service/UploadRecordService.java#L68-L84) | enqueue는 engine 활성 여부를 본다. 로컬 transport만 꺼도 engine이 켜져 있으면 공유 DB에 PENDING 작업을 넣어 개발 dispatcher가 가져갈 수 있다. |

따라서 **DB를 공유한 채 큐만 나누는 방식은 기본 격리안으로 사용하지 않는다.**
jobId 접두사·시험 계정만 구분해도 위 조회 조건은 바뀌지 않는다.
engine을 꺼도 업로드 자체의 공유 DB 쓰기는 별개이므로 기능 토글만으로 전체 시험을 격리했다고 판단하지 않는다.
실제 DB의 수동 RLS·별도 schema·권한 경계는 미확인이다. 코드상 가능성을 현재 장애 발생의 증거로 확대하지 않는다.

## 기본 격리·접근 계약

| 요소 | 기본 구성 | 접근 경계 |
|---|---|---|
| DB | 로컬 PostgreSQL의 시험 전용 DB. 업무 테이블·engine_jobs·AI view를 함께 분리 | Server의 시험 업무 쓰기와 AI의 승인 view SELECT를 구분한다. 개발 DB DSN·Secret을 주입하지 않는다. |
| 메시지 | SQS 호환 로컬 브로커의 시험 전용 jobs/results 큐 한 쌍 | Server는 작업 발행·결과 소비, AI는 작업 소비·결과 발행을 맡는다. 개발 큐 URL은 사용하지 않는다. |
| 원본 | 시험 전용 파일 트리/volume | Server 읽기·쓰기, AI 읽기 전용. 컨테이너별 mount 경로가 달라도 같은 원본 트리로 연결한다. |
| 설정·인증 | 시험 전용 설정 묶음과 인증 전달 경로 | 개발 프로필·실제 AWS 자격증명·Secret을 상속하지 않는다. 값 대신 이름·용도·전달 책임을 문서화한다. |
| 네트워크·검증 | 개발 DB·큐·bucket에 접근하지 못하는 시험 경계 | 기동 전에 대상 DB·endpoint·큐 URL·원본 경로를 대조한다. 브로커의 필요한 API·결과 메시지 크기 계약을 실제 연동 전에 확인한다. |

같은 PostgreSQL 인스턴스라도 별도 논리 DB로 시작할 수 있다. 새 클라우드 DB 인스턴스가 필수인 것은 아니다.
별도 schema를 선택하려면 JDBC/JPA·view·role·search_path 전체 경계를 입증해야 한다.
공유 engine_jobs를 유지해야 한다면 Server에서 명시적 작업 소유권을 설계하고 별도 이슈·PR로 검토한다.
기존 개발 worker를 중지하거나 개발 작업을 시험 큐로 재발행하는 방식을 격리 수단으로 사용하지 않는다.

## Server·AI 연결 계약

| 항목 | Server | AI |
|---|---|---|
| DB | datasource를 시험 전용 DB로 고정하고 schema·view·migration·업무 쓰기를 관리 | DATABASE_URL은 같은 시험 DB의 승인된 read-only role로 연결 |
| 큐 | IPGO_SQS_ENDPOINT와 시험 jobs/results URL을 함께 지정 | AWS_ENDPOINT_URL_SQS와 같은 시험 jobs/results URL을 함께 지정 |
| 원본 | IPGO_UPLOAD_STORAGE=local, IPGO_UPLOAD_DIR로 시험 트리에 저장 | STORAGE_BASE를 같은 트리로 연결하고 IPGO_UPLOAD_BUCKET은 설정하지 않음 |
| 엔진 | 격리·접근 확인 후 IPGO_ENGINE_ENABLED 및 IPGO_ENGINE_TRANSPORT_ENABLED 활성화 | ENGINE_MODE=real, IPGO_EMBEDDED_WORKER_ENABLED=true로 시험 worker 실행 |

Server의 설정 연결은 [application.yaml](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/resources/application.yaml#L58-L65)과
[SQS endpointOverride](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/infrastructure/EngineTransport.java#L30-L41)에 있다.
AI의 서비스별 endpoint 환경변수는 [AWS 공식 설정](https://docs.aws.amazon.com/sdkref/latest/guide/feature-ss-endpoints.html)과
[SQS 식별자](https://docs.aws.amazon.com/sdkref/latest/guide/ss-endpoints-table.html)를 따른다.
점검 시 boto3 1.43.121·botocore 1.43.127에서 가짜 인증값으로 클라이언트 설정만 해석해 로컬 endpoint 선택을 확인했다.
실제 브로커나 AWS API는 호출하지 않았으며 API 호환성·메시지 처리 성공은 미검증이다.
현재 단계에서 endpoint 기능 추가 코드를 요구할 근거는 없다.

Server는 [userId/UUID 트리](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/infrastructure/storage/LocalUploadStorage.java#L78-L95)에 original.xlsx를 저장한다.
AI는 [storageKey 기반 원본 읽기](https://github.com/IpgoITGO/ipgo-ai/blob/b2f685fc852e524a079c20fc5d8d6a7eb2791f37/app/storage.py#L21-L57)를 사용한다.
AI에 bucket 설정이 남으면 STORAGE_BASE보다 S3를 먼저 사용하므로 파일 기반 시험에서는 bucket을 비워야 한다.
원격 개발 worker가 로컬 파일을 읽을 수 있다고 가정하지 않는다.

DB 원본 모드는 기본안에서 선택하지 않는다. 별도로 선택하면 db/ storageKey 분기와
[AI 원본 조회 계약](https://github.com/IpgoITGO/ipgo-ai/blob/b2f685fc852e524a079c20fc5d8d6a7eb2791f37/app/repository.py#L16-L34)에 맞춰
시험 DB의 IPGO_ORIGINAL_DATABASE_URL·ipgo_ai_service_reader·원본 view 권한을 Server와 함께 준비한다.

## 실제 AWS 연동이 필요한 경우

독립 로컬 DB는 유지하고, 필요한 경우에만 시험 전용 jobs/results와 원본 저장소를 별도 승인 후 준비한다.
양쪽에서 파일을 공유할 수 있다면 S3는 생략한다. S3가 필요하면 시험 전용 bucket을 우선 검토한다.
[현재 Server S3 key 생성](https://github.com/IpgoITGO/ipgo-server/blob/55bdc6533c083afa0dee5bbcf5a739f147cb746d/src/main/java/com/ipgo/server/infrastructure/storage/S3UploadStorage.java#L78-L85)은
userId/UUID/original.xlsx이므로 임의 시험 prefix 추가를 설정만으로 해결한다고 가정하지 않는다.
공유 bucket의 새 prefix가 필요하면 별도 Server 변경을 검토한다.

- Server는 시험 jobs의 SendMessage, 시험 results의 ReceiveMessage/DeleteMessage에 한정한다.
- AI는 시험 jobs의 ReceiveMessage/DeleteMessage, 시험 results의 SendMessage에 한정한다.
- S3를 쓰면 시험 bucket의 Server 쓰기·AI 읽기만 허용하고 개발 자원 권한을 주지 않는다.
- 운영 검증용 큐 속성 조회 권한은 별도 주체로 검토하며 runtime 권한을 관성적으로 추가하지 않는다.

자원·Secret·IAM·비용과 보존/정리 책임을 구체화한 뒤 승인받는다. 이 문서 PR로 AWS 변경을 실행하지 않는다.

## 담당 범위

| 담당 | 책임 |
|---|---|
| Infra #68 | DB·메시지·원본의 자원/접근 경계, endpoint와 전달 책임, 공유 허용 여부, 필요 자원·비용·보존/정리 계약 |
| Server | dispatcher 작업 선택·결과 수신 근거 확인, 시험 schema/view/role·migration·합성 자료 준비, 원본 저장과 DONE/FAILED 반영, 후속 계산 범위 구분 |
| AI #57 | 계약에 맞는 worker·DB/원본 연결, 처리·결과 발행·실패 경로 검증과 새 개발자 재현 안내 |
| 공동 | 같은 시험 경계인지 확인하고 간섭 없음의 근거·실행 식별자·미검증 범위를 기록 |

## 적용 순서

1. Server에서 위 작업 선택·만료·결과 반영 근거를 확인하고 시험 DB·원본 모드와 계산 검증 범위를 정한다.
2. Infra에서 기본안과 접근 경계·자원 필요 여부·보존/정리 책임을 검토해 계약을 확정한다.
3. 필요한 변경만 레포별 이슈·PR로 준비한다. 실제 환경 구축·AWS 설정 변경·비용·데이터 영향은 별도 승인받는다.
4. 대상 DB·endpoint·큐 쌍·원본 트리를 대조한 뒤 엔진을 켜고, 새 합성 uploadId/jobId로 성공·실패 경로를 시험한다.
5. 다른 시험 환경의 작업·데이터 불변과 결과 수신 분리를 확인하고 정제·후속 계산·실사용 검증을 구분해 기록한다.

문서 초안과 구현 준비는 병행할 수 있지만 격리 계약과 Server 확인 없이 실제 연동 시험을 시작하지 않는다.

## 완료 조건과 중단 기준

### 계약 문서 검토

- [ ] Server 점검 근거와 같은 DB/큐에서의 간섭 조건이 확인돼 있다.
- [ ] 각 프로세스의 DB·큐·원본·접근 주체와 설정 전달 책임이 명확하다.
- [ ] 새 AWS 자원 필요 여부와 미구축·미검증 항목을 분리했다.
- [ ] Server·AI 담당 범위, 후속 이슈·적용 순서와 완료 판단이 연결돼 있다.

### 후속 환경·연동 시험

- [ ] 모든 연결 대상이 시험 경계에 속하고 개발 자격증명이 포함되지 않았다는 근거가 있다.
- [ ] 새 유효 합성 원본에서 CLEAN → 결과 저장 → DONE을 확인했다.
- [ ] 잘못된 합성 원본에서 FAILED와 사유를 확인했다.
- [ ] 폐기 가능한 독립 시험 환경 B의 작업·업로드·결과 큐를 환경 A가 소비·실패·마감·삭제하지 않는다.
- [ ] 원본 경로·권한이 일치하고 정제와 자동 파생 CALCULATE의 확인 범위가 구분돼 있다.
- [ ] 시험 자원 보존 기간·정리 책임·접근정보 폐기 방법이 기록돼 있다.

공유 작업 테이블이나 공유 결과 큐가 남아 있거나, 실제 연결 대상이 불명확하면 통합 시험을 중단한다.
부정 시험용 데이터도 폐기 가능한 로컬 환경에만 준비한다. 실제 개발 작업을 일부러 흘리거나 실패 처리하지 않는다.
queue purge·기존 업로드 삭제·수동 DONE·개발 worker 중지로 시험을 맞추지 않는다.

## 검증 한계와 변경 취소

이번 근거는 코드·설정 연결·관련 기존 테스트의 정적 대조와 SDK endpoint 해석이다.
기존 테스트를 읽었다는 사실은 이번 테스트 실행 성공이 아니다. DB/브로커 구축·실제 메시지·업무 E2E·부하/장기 안정성은 미검증이다.
설정 목록은 연결 가능한 경로를 정리한 것이며 시험 환경 완성을 보증하지 않는다.
문서 PR 생성·병합만으로 Infra #68 또는 AI #57의 실제 연동 완료를 처리하지 않는다.

문서만 변경한 단계에서는 운영 복구가 필요하지 않으며 문서는 revert할 수 있다.
후속 시험 자원 정리는 승인된 시험 자원에 한정하고 개발 Server·AI·DB·큐를 복구 대상으로 바꾸지 않는다.

# 0002. Spring Boot와 FastAPI 데이터 접근 계약

- 상태: 결정
- 날짜: 2026-10-29

## 결정

Spring Boot가 업무 DB와 상태 변경을 소유하고 FastAPI는 계산에 필요한 데이터를 조회만 합니다.

| 주체 | 허용 | 금지 |
|---|---|---|
| Flyway migration role | schema 생성·변경 | 애플리케이션 런타임 사용 |
| Spring application role | 업무 데이터 SELECT·INSERT·UPDATE·DELETE | 임의 schema 변경 |
| FastAPI reader role | 승인된 계산용 view와 필요한 table SELECT | INSERT·UPDATE·DELETE·DDL |

Spring Boot가 DB를 소유한다는 의미와 런타임 계정에 DDL 권한을 주는 것은 구분합니다. 운영에서는 migration, server runtime, AI reader 자격 증명을 각각 분리합니다.

## 계산용 view

FastAPI는 내부 table 구조 대신 다음 목적의 안정된 view 계약을 사용합니다.

- 유효한 업로드와 source file
- 상품과 재고관리단위
- 일별 재고 기록
- 입고 조건
- 기존 발주 물량
- 계산 대상과 재현용 source 정보

정확한 view 이름과 column은 서버 migration Issue에서 확정합니다. view 변경은 FastAPI schema 호환성 검증과 함께 배포합니다.

## S3와 SQS

- Spring task role: 업로드 bucket 읽기·쓰기, job 전송, result 소비
- FastAPI task role: 업로드 bucket 읽기, job 소비, result 전송
- 삭제와 lifecycle 변경은 애플리케이션 task role에 부여하지 않습니다.
- 계산 결과의 최종 검증과 DB 저장은 Spring Boot만 수행합니다.

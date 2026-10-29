# 0001. 인프라 저장소 경계

- 상태: 결정
- 날짜: 2026-10-29

## 결정

AWS 공통 인프라는 공개 조직 저장소 `IpgoITGO/ipgo-infra`에서 관리합니다. 애플리케이션 저장소와 인프라 저장소의 책임을 분리합니다.

| 저장소 | 책임 |
|---|---|
| `ipgo-client` | React, Vercel, 브라우저 연동 |
| `ipgo-server` | Spring Boot, Flyway, 서버 image |
| `ipgo-ai` | FastAPI, 계산 엔진, AI image |
| `ipgo-infra` | AWS 공통 자원, IAM, Terraform, 운영 문서 |

공개 저장소에는 실제 Secret 값, Terraform state, plan 파일, 내부 운영 endpoint와 사용자 데이터가 포함되지 않습니다. 프로젝트 완성 시점의 private 전환은 저장소 공개 이력에 이미 노출된 내용을 회수하지 못하므로, 처음부터 공개 가능한 내용만 기록합니다.

## 이유

VPC, RDS, S3, SQS, ECS와 IAM은 서버와 AI가 함께 사용합니다. 이를 한 애플리케이션 저장소에 두면 공통 자원의 소유권과 변경 검토가 특정 서비스에 종속됩니다.

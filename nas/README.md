# NAS 단일 호스트 개발 환경

AWS 개발 계정 접근이 끊긴 뒤(2026-11) 개발 환경을 NAS 한 대로 옮긴 구성이다.
기존 `terraform/`과 AWS 문서는 이전 구성 기록으로 남겨 둔다.

## 구성

| AWS에서 쓰던 것 | NAS 구성 | 비고 |
|---|---|---|
| ECS Server | `server` (Server 저장소 `Dockerfile`) | NAS loopback `127.0.0.1:18090`만 연다 |
| ECS AI + embedded worker | `ai` (AI 저장소 `Dockerfile`) | 외부 포트 없음 |
| RDS PostgreSQL | `postgres` (18.7) | named volume `pg-data` |
| DB 역할·Flyway 작업 | `db-bootstrap` → `db-migrate` (Server `Dockerfile.database`) | V1–V35, 앱 계정은 DDL 권한 없음 |
| SQS jobs/results + DLQ | `elasticmq` | 900초/120초, 5회 실패 시 DLQ, 크기 제한 완화 |
| S3 업로드 원본 | named volume `uploads` | Server 쓰기, AI 읽기 전용 |
| Secrets Manager | NAS의 `.env` (권한 600) | 저장소에 넣지 않는다 |
| 모델 이미지 내장 | LGBM19 묶음을 읽기 전용 볼륨으로 연결 | 모델 교체 시 이미지 재빌드 불필요 |
| Lambda·Step Functions(야간 RDS 정지), Budgets | 없음 | AWS 비용 통제용이었다 |

메일·토스 결제·LLM 설명은 비밀값을 새로 발급한 뒤 켠다. 지금은 모두 꺼져 있다.

## 처음 실행

경로는 예시다. 비밀값은 화면에 출력하지 않는다.

```bash
R=/home/iwh/apps/IpgoITGO/nas-runtime          # compose 밖의 실행 디렉터리(권한 700)
git clone https://github.com/IpgoITGO/ipgo-server.git "$R/src/ipgo-server-<sha7>"   # 승인한 SHA로 checkout
git clone https://github.com/IpgoITGO/ipgo-ai.git "$R/src/ipgo-ai-<sha7>"
# 모델 묶음(manifest.json 포함)을 $R/model/<modelVersion>에 두고 디렉터리 755·파일 644로 맞춘다.
nas/scripts/init-env.sh "$R" "$R/src/ipgo-server-<sha7>" "$R/src/ipgo-ai-<sha7>" \
  "$R/model/<modelVersion>" <modelVersion>

C="docker compose -f nas/compose.yaml --env-file $R/.env"
python3 /home/iwh/scripts/nas-build-guard/workload.py --kind build -- $C build db-bootstrap server ai
$C up -d
$C ps
curl -s http://127.0.0.1:18090/actuator/health
```

`db-bootstrap`과 `db-migrate`는 실행 후 종료(`Exited (0)`)가 정상이다.

## 메모리 한도

| 서비스 | 한도 |
|---|---|
| server | 640 MiB (Java heap 256 MiB) |
| ai | 512 MiB |
| postgres | 384 MiB |
| elasticmq | 128 MiB |
| 일회성 DB 작업 | 256 MiB |

2026-11-24 첫 실행에서 계산 1회 뒤 실제 사용량은 server 약 400 MiB, ai 165 MiB, postgres 67 MiB, elasticmq 25 MiB였다.

## 내부 검증 (2026-11-24, Server `15af5aa` · AI `d63411d` · 모델 `lgbm19-60a4d15301cd5490`)

compose 네트워크 안에서 합성 자료로 확인했다. 실제 고객 자료와 유료 LLM 호출은 쓰지 않았다.

- DB 역할 4개 bootstrap, Flyway V1–V35 적용, AI 계정은 `users` 조회·`engine_jobs` 수정·스키마 생성 불가
- Server·AI health 정상, 합성 회원 로그인
- 이번 달 합성 수불부 업로드 → AI 정제 `DONE` → LGBM19 계산 `DONE` (모델 fallback 없음)
- 형식이 틀린 파일은 접수 단계에서 `400 UPLOAD_INVALID_FORMAT`
- LLM 설명 호출 0건

## 알려진 한계

- ElasticMQ는 메시지를 메모리에만 둔다. 컨테이너가 재시작되면 처리 대기 중인 계산 메시지가 사라질 수 있다.
- 외부 공개(nginx·인증서·DNS)는 다음 단계다. 그 전까지 `IPGO_AUTH_COOKIE_SECURE=false`다.

## 되돌리기

```bash
$C down          # 컨테이너만 내리고 DB·업로드 볼륨은 남긴다
$C down -v       # DB·업로드 볼륨까지 삭제한다(되돌릴 수 없음)
```

# 개발 인증 메일 설정 준비

Server #82의 Gmail 개발·시연용 SMTP 연결을 준비한다. 메일 발송/Secret/IAM/태스크 변경은 이 문서나
후보 생성기 실행으로 승인되지 않는다. 실제 LLM·AI·DB schema·Production은 변경 대상이 아니다.

## 로컬 준비

`scripts/onebox/prepare-server-mail.py`는 공식 AWS MCP에서 읽은 **현재 실행 서비스의** DescribeTaskDefinition
JSON을 받아 등록 후보만 생성한다. 현재 서버의 family/revision·이미지·계정·서울 리전·EC2 bridge 구성을
입력과 대조한다. 이미지·역할·메모리·헬스·기존 DB/JWT 매핑·다른 컨테이너를 유지하고 메일 항목만 바꾼다.
Terraform의 오래된 bootstrap/Fargate 정의를 통째로 적용하지 않는다.

기존 [Infra PR34](https://github.com/IpgoITGO/ipgo-infra/pull/34)의 전용 password Secret을 재사용한다.
이 PR은 Secret 메타데이터와 execution role의 읽기 권한을 준비하며 이 생성기는 별도 리소스를 만들지 않는다.
SMTP 일반 설정은 `MAIL_ENV`, 계정·발신 주소는 비공개 JSON의 `SPRING_MAIL_USERNAME`·`IPGO_MAIL_FROM`
두 항목으로 추가한다. 비밀번호는 그 JSON에 넣지 않으며 ECS `SPRING_MAIL_PASSWORD`는 Secret 전체 ARN을
직접 참조한다. 단일 문자열 Secret에 JSON 키 suffix를 붙이지 않는다. 입력은 0600 파일, 출력은 새 0700
디렉터리의 0600 파일로 보관한다.

```text
python3 scripts/onebox/prepare-server-mail.py
  --input <공식 MCP로 읽은 비공개 정의 JSON>
  --expected-definition <읽기로 고정한 현재 TD ARN>
  --expected-image <같은 TD의 정확한 서버 이미지>
  --secret-arn <PR34의 전용 password Secret 전체 ARN>
  --mail-config <계정·발신 주소만 있는 비공개 0600 JSON>
  --output-dir <새 비공개 후보 디렉터리>
```

위는 인수 설명이며 실제 비밀값/리소스 주소를 문서에 채우지 않는다. 셸에서 실행할 때 줄 연결과
경로 인용을 적용한다. 출력 `task-definition.json`, `required-secret-access.json`, `manifest.json`을 검토한다.
manifest는 원본/후보 해시와 배포 미승인 표시를 보존한다. 생성기는 AWS API·셸 명령·네트워크를 호출하지 않는다.

## 적용 전 별도 승인 대상

1. 팀이 관리하는 앱 비밀번호의 안전한 기존 보관 경로와 실제 수신자 1명을 확인한다. 채팅/Issue에 비밀번호를 쓰지 않는다.
2. 전용 SMTP Secret이 없으면 PR34 경로의 Secret 생성·안전한 단일 문자열 값 입력과 추가 저장 비용을 승인받는다. 기존 DB/JWT/LLM Secret을 재사용하지 않는다.
3. **현재 서버 execution role**에 해당 Secret 한 개의 GetSecretValue 권한을 PR34 Terraform 경로로 추가한다. 후보의 required-secret-access는 대조용이며 별도 수동 IAM 정책을 중복 적용하지 않는다. 기존 정책을 교체하거나 조회 역할/AI task role에 추가하지 않는다. 고객 관리 KMS 키를 사용한다면 키 정책·제한된 Decrypt 권한을 별도 검토하며 이 후보 정책이 모두 처리한다고 가정하지 않는다.
4. 새 TD 등록·Server만 단회 rollout하는 기존 Actions/OIDC 경로와 승인 SHA·환경을 확인한다. 기존 24시간 관측의 고정 source/TD 조건과 충돌할 수 있으므로 관측 담당과 새 검증 창/관측 경계를 먼저 정한다. 임의 중지/재예약하지 않는다.
5. 저장 응답 runId 헤더를 추가하는 Server 코드 변경도 같은 배포에 포함할지 SHA와 영향을 명시한다. 기존 SHA 승인을 최신 dev로 확대하지 않는다.
6. 코드/설정/정책의 사본과 이전 TD ARN을 보관하고, 새 Secret 값 유효성/JSON 키/role 접근·SMTP 포트를 확인한다. Secret 값을 로그로 조회하지 않는다.

## 실제 검증과 복구

새 태스크의 source/digest·기동/헬스·기존 API 읽기부터 확인한다. 승인 수신자에게 메일 요청1회→수신함
실제 도착→코드 확인→가입→로그인 순서로 검증한다. 202는 발송 수락이고 실제 수신 성공과 구분한다.
이 과정은 인증 DB와 새 시험 사용자/창고를 만든다. 대상과 보존 범위를 별도 승인받는다.

문제가 생기면 새 발송/가입을 중단한다. 승인된 이전 TD로 되돌려 기존 로그인/계산 흐름을 확인한다.
PR34에서 추가한 권한 참조의 원복은 해당 Terraform 검토 경로를 따르며 기존 정책은 유지한다. Secret 삭제·새 사용자/파일 정리는 별도 승인 전
실행하지 않는다. 메일을 보냈다면 발송 사실과 DB rollback의 가능 범위를 분리한다.

```bash
python3 -m unittest discover -s scripts/onebox -p test_prepare_server_mail.py -v
```

이 검사는 오프라인 후보의 보존/차단 규칙을 검증한다. AWS 적용·SMTP 연결·실제 메일 수신의 증거는 아니다.

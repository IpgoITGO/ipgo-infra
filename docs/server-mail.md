# 개발 서버 Gmail SMTP secret

관련 작업: [Server #82](https://github.com/IpgoITGO/ipgo-server/issues/82).

## Terraform 변경 범위

- 서울 리전에 `/ipgo/dev/server-mail-password` secret 메타데이터를 정의합니다.
- 서버 execution role의 기존 DB/JWT 읽기 권한을 보존하고, 이 secret의 `secretsmanager:GetSecretValue` 권한만 추가합니다.
- 앱 task role·호스트·조회 역할의 권한과 ECS task definition·서비스는 변경하지 않습니다.
- 비밀번호 값은 `aws_secretsmanager_secret_version`으로 관리하지 않으며 Terraform state·plan·소스에 넣지 않습니다.

Secret 1개를 추가하므로 월 보관료와 호출료가 늘어납니다. 실제 apply 전 [AWS 공식 요금](https://aws.amazon.com/secrets-manager/pricing/)과 적용 기간을 확인합니다. 생성된 secret은 기본 AWS 관리형 Secrets Manager 암호화 키를 사용하며 삭제 복구 유예는 7일입니다.

## 단계별 적용과 검증

1. 같은 저장소의 `dev` 대상 PR에서 기존 `Terraform dev plan`을 실행합니다. 성공한 run의 소스 SHA·환경과 변경 주소를 확인합니다. 예상 관리 리소스는 secret 생성 1개·서버 execution role 정책 갱신 1개이며 삭제/교체는 없습니다. 다른 변경이 있으면 apply 전에 따로 검토합니다.
2. plan 검토 후 별도 승인을 받아 고정된 Infra SHA를 기존 보호된 `Terraform dev apply` 경로로 적용합니다. PR 게시나 plan 성공은 apply 승인이 아닙니다.
3. 계정 담당자가 승인된 secret에 Gmail 앱 비밀번호 원문을 안전하게 입력합니다. JSON이나 Gmail 로그인 비밀번호를 넣지 않습니다. 값은 채팅·Issue·workflow 입력/로그에 남기지 않습니다. `AWSCURRENT` 메타데이터 존재만 확인하며 이 확인을 비밀번호 유효성 검증으로 확대하지 않습니다.
4. 서버 메일 환경변수와 `SPRING_MAIL_PASSWORD` secret ARN 연결은 별도 서버 설정 배포로 검토합니다. 이 Terraform 변경만으로 메일 발송이 활성화되지는 않습니다. 새 태스크가 기동될 때 secret이 주입되므로 기존 태스크는 자동 갱신되지 않습니다.
5. 재시작 영향·기존 코드/설정 보존·이전 태스크로 복구하는 절차를 승인받은 뒤 배포합니다. 실제 메일 수신·코드 확인·가입·로그인과 해당 시험의 데이터 변경을 별도로 승인·검증합니다.

## 복구

서버 설정 배포가 실패하면 서버 서비스의 이전 task definition으로 먼저 복귀하고 앱 health를 확인합니다. DB·기존 secret·AI 서비스는 복구 대상으로 바꾸지 않습니다. 신규 secret과 permission은 자동 삭제하지 않으며, 참조가 없음을 확인한 뒤 별도 승인으로 추가 ARN 권한과 secret 정리를 결정합니다. Terraform 코드를 통째로 되돌려 secret 삭제를 유발하지 않습니다.

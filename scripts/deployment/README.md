# 배포 증거 인계와 전체 시간 기록

이 도구는 JSON·로그를 로컬에서 대조한다. 배포·환경 승인·Terraform apply·DB 변경·유료 요청을
실행하지 않는다. 실제 계정/환경/source/workflow SHA·영향·복구 범위를 승인받고 기존 배포
절차를 수행하는 담당자가 사용한다. 소스 CI 통과·배포 성공·앱 헬스·실제 업무 성공을 구분한다.

## 준비와 안전 경계

- 준비 시작부터 승인 대기·DB 선행 작업·앱 교체·독립 검증·최종 문서 저장까지 시간을 기록한다.
  앱 Actions 합계를 전체 배포 시간으로 부르거나 사전 준비를 측정 밖으로 옮기지 않는다.
- service discovery·현재 환경 설정·실제 RDS managed Secret 참조·지원 API/인증 경로·workflow/
  환경 ID·검증 도구는 실행 전에 준비한다. 실제 작업 중 도구를 새로 구현하지 않는다.
- DB의 migration/checksum/schema·잠금은 실제 읽기로 확인한다. 변경이 없을 때만 DB task/
  이미지 게시 재실행을 생략하고, 준비 시간에 읽기를 포함한다. 새 migration을 생략하지 않는다.
- 독립 읽기만 묶는다. Server 검증 후 AI, 그 뒤 Client를 배포하는 순서를 유지한다.
  다음 실행 대상의 정확 source/workflow SHA·현재 runtime·환경 승인은 쓰기 직전 다시 확인한다.
  이미 배포한 상위 저장소의 dev만 전진했다면 새 SHA를 대기로 기록하며 임의로 배포하지 않는다.
- rollout·정확 이미지 digest·HEALTHY·앱 HTTP·변경 설정·다른 서비스 보존·복구 검사는 유지한다.
  앱 외 시간 예산을 초과해도 안전 검사를 생략하지 않는다. 총 10분대와 단축 효과는 실제로 측정한다.

## AWS 읽기 수집

`collect_aws.py`는 공식 AWS MCP run_script에 함수 정의를 전달할 때 사용한다.
로컬 AWS CLI/SDK를 실행하는 스크립트가 아니다. 함수 정의 뒤에 승인 대상 리전·cluster와
직전 snapshot의 service→TD 기준을 넣어 `await collect_deployment(...)`를 호출한다.
도구/API 성공과 전체 페이지를 확인하고 반환된 snapshot만 보호 경로에 저장한다.
환경값과 Secret 원문은 반환하지 않는다. 설정 차이는 경로와 허용된 기능 설정만 반환한다.
권한 부족은 누락된 데이터를 성공으로 채우거나 역할 권한을 추가하는 이유가 아니다.

## 검증과 인계

```bash
python3 scripts/deployment/review.py preflight /보호경로/preflight.json
python3 scripts/deployment/review.py run /보호경로/run-bundle.json
python3 scripts/deployment/session.py handoff /보호경로 server
python3 scripts/deployment/session.py handoff /보호경로 ai
```

최초 `preflight.json`은 `plan`, `before`, `sources`를 가진다. `plan`에는 승인한 account/region/
cluster와 server/ai 각각의 전체 source_sha/workflow_sha·workflow_id/environment_id를 둔다.
`sources`에는 branch·정확한 성공 push CI run·모든 필수 jobs 원문을 둔다.

인계 입력은 대상별 `server/ai-dispatch.json`, `-run.json`, `-jobs.json`, `-after.json`,
`-job.log`다. dispatch는 실제 제출한 ref/inputs, 나머지는 실제 성공한 도구 응답이다.
Server에는 snapshot 이후 GET한 `server-http.json`(observed_at/http_status/body)도 필요하다.
시작 시각 변경이 명시 승인됐을 때만 `approved-server-start-change.json`에 from/to와
approval_reference를 둔다. 다른 환경변수/Secret/설정 변경을 포괄 승인하지 않는다.

`handoff`는 기존 runtime 검증을 그대로 호출하고 `*-verify.json`과 `*-receipt.json`을 새로
쓴다. AI before에는 검증한 Server snapshot을 자동 사용한다. 저장된 bundle/log hash 변경,
실패·stale·누락·추가 설정 변경은 거부한다. 5분을 넘은 after/HTTP와 1시간 초과 baseline은
live 검증에 쓸 수 없다. 과거 재생에는 `--replay`가 필요하며 replay 영수증은 live 인계에 거부된다.
이미 저장한 결과를 덮어쓰지 않는다. 인계 성공도 다음 배포나 환경 승인을 자동 허용하지 않는다.

## 마감 시간 보고

```bash
python3 scripts/deployment/review.py timing /보호경로/timing-bundle.json --full-pipeline
python3 scripts/deployment/session.py audit /보호경로/timing-bundle.json \
  --client-run /보호경로/client-run.json --report /새경로/시간보고.md
```

timing-bundle은 실제 started_at/finished_at/provenance, server/ai 각각의 run, 6개 phases를
가진다. phase는 preparation/database/server/ai/client/final_verification_and_record 순이며
각각 name/started_at/finished_at/status를 둔다. 서로 겹치거나 빈틈이 있으면 거부한다.
생략 단계는 동일 시작/종료, skipped와 reason이 필요하다. 마감은 최종 문서 저장까지 포함한다.
`audit`는 별도 client run도 대조해 세 Actions와 앱 외 4구간·전체 시간을 한 번 집계한다.
기록 자체가 승인이나 업무 성공·새 단축 실측의 증거는 아니다. 과거 재생을 새 성공에 합산하지 않는다.
정본에는 보고서 링크와 현재 상태를 남기고 시간표를 여러 문서에 수작업으로 복제하지 않는다.

## 증거 보호와 테스트

실제 증거는 저장소 밖 보호 디렉터리0700/파일0600에 둔다. Secret 값·인증정보·개인정보,
환경 파일·원본 업무 자료·실제 배포 로그를 commit하지 않는다. 출력의 authorization_granted는
항상 false이며, 잘못된 입력의 원문/예외 본문도 출력하지 않는다.

```bash
python3 -m unittest discover -s scripts/deployment -p 'test_*.py' -v
```

테스트는 합성 AWS/JSON만 사용한다. 새 CI job도 자격 증명이나 AWS/DB 접속 없이 실행한다.

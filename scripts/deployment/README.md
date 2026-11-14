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

`python3 scripts/deployment/test_session.py`로 인계·로컬 검증·마감 보호 검사를 직접 실행할 수도 있습니다.
`python3 scripts/deployment/test_ci_complete.py`는 CI 수집 검사8개를 직접 실행합니다.
파일 끝의 진입점이 모든 검사 정의 뒤에 있어 직접 실행과 해당 파일 discovery가 같은 검사를 실행합니다.

테스트는 합성 AWS/JSON만 사용한다. 새 CI job도 자격 증명이나 AWS/DB 접속 없이 실행한다.

## 로컬 서버 검증과 작업 마감

Server의 `scripts/testing/local-gradle.sh`는 사용자 소유 캐시로 기존 Gradle 검사를 실행합니다.
이 저장소는 검증 결과 집계와 원장만 담당하며 AWS·DB 연결이나 배포를 실행하지 않습니다.

- `worklog.py start/stage/check/skip/finish`로 준비부터 최종 기록까지 시간을 남깁니다.
  실제 업무(`actual`), 합성 검사(`synthetic`), 재생(`replay`)을 분리합니다. 명령별 인자는 `--help`로 확인합니다.
- `session.py server-complete DIRECTORY --worktree WORKTREE --observed-at ISO_TIME --java-exit 0 --python-exit 0`는
  원장의 `final-source-hashes.json`, `java-finished.txt`, JUnit XML, JAR와 종료 코드를 대조합니다.
  `server-validation.json`과 XML 사본을 한 번만 보존하며 사람의 최종 검토는 별도로 남깁니다.
- Code Mode에서 `code-mode-flow.js`를 AsyncFunction 본문으로 실행할 때 `plan`에
  `tools_directory`(이 도구 폴더의 절대경로), `directory`(저장소 밖 `.private/작업ID`)를 전달합니다.
  `mode: 'server-local'`에는 `worktree`, 실행 중인 `session_id`와 선택 `initial_output`이 필요합니다.
  같은 실행을 30초 단위로 기다린 뒤 결과를 한 번 수집하고 documentation 단계로 전환합니다.
- `mode: 'close'`는 `event_id`와 선택 `complete_goal`, `comparison_plan`을 받습니다.
  finalization 단계와 `validation_passed: true`인 `completion.json`이 있어야 합니다.
  `codex-route`가 설치된 환경에서만 사용하며 미안내 출력 알림이 있으면 종료를 멈춥니다.
  알림 안내·확인, 사람 검토, 승인 판단을 자동 처리하지 않습니다. 비교 원장을 명시하지 않으면 시간 비교를 만들지 않습니다.

```bash
node --test scripts/deployment/test_code_mode_flow.cjs
```

이 검사는 합성 도구 응답만 사용합니다. 통과 자체가 실제 업무 시간 단축이나 배포 승인을 뜻하지 않습니다.


## GitHub CI 회수부터 기록 단계까지

`session.py ci-complete DIRECTORY --plan DIRECTORY/ci-plan.json`은 기존 실행을 기다리는
읽기 전용 호출입니다. CLI 인자를 매번 조립하지 않고 아래 계획을 사용합니다.

```json
{"repo":"IpgoITGO/ipgo-server","run_id":123,"sha":"검토한40자리SHA",
 "branch":"dev","event":"push","workflow":".github/workflows/test.yml",
 "jobs":["deploy-contract","test","container","arm-test"]}
```

원장을 validation 단계로 전환한 후 실행합니다. REST run 상태를 5초 간격으로 조회하고 완료 뒤 jobs를 한 번만
조회하며 읽기 전용 호출만 사용하며 dispatch·merge·승인·배포를 호출하지 않습니다.
정확 SHA·branch·event·workflow·필수 job 집합과 모든 성공 상태를 확인합니다.
누락·추가 job·skip·실패·계획 변경은 거부하며 원본/실패 로그를 덮어쓰지 않습니다.
필수 workflow가 여러 개면 각각의 근거가 필요하며 이 단일 run 영수증으로 대체하지 않습니다.

성공 시 보호된 run/jobs 원본과 `ci-validation.json`을 보존하고 같은 실행에서 documentation으로
전환합니다. 사람 검토와 승인, 전체 업무 완료는 별도입니다. Code Mode에서는 기존 본문에
`mode: 'github-ci'`와 `tools_directory`, `directory`만 전달하면 같은 실행 handle을 연속 대기합니다.
결과 정본은 `completion.json`, PR/상태 문서는 짧은 결과와 근거 링크만 사용합니다.
마감은 기존 `mode: 'close'`로 알림 확인→Goal→원장 종료를 이어서 처리합니다.
쓰기 직전 fresh 확인과 병합 뒤 정확 SHA 검증은 생략하지 않습니다.


`ci-profile.json`은 perf_counter 경과시간, process_time Python CPU, RUSAGE_CHILDREN gh CPU,
명시적 poll sleep과 CLI 실행 시간을 기록합니다. CLI의 CPU 제외 시간은 네트워크·프로세스 시작·
스케줄링을 함께 포함하므로 순수 네트워크 시간으로 표시하지 않습니다. 원격 CI worker의 CPU는
GitHub jobs API로 관측할 수 없으며 job 경과시간과 구분합니다. 5초는 조회 간격이며 API 응답/공개
지연까지 포함한 감지 상한을 보장하지 않습니다. 요청당 30초/전체 30분 제한을 두고 API 오류는
원본을 보존한 뒤 중단합니다. 성공 polling을 자동 재시도 실패로 세지 않으며 실패 요청을 재전송하지 않습니다.


## CI 시작 전에 마감 연결

기존 close 모드에 실행 중인 `session_id`를 선택적으로 전달하면 같은 실행 종료를 연속 대기한 뒤
close-check→알림 확인→Goal→원장 종료를 연결합니다. CI/문서 기록 프로세스를 시작한 직후
이 모드를 등록하며 종료 뒤 새 마감 코드를 작성하지 않습니다. 종료 코드 실패·미완료 증거·
미안내 알림이 있으면 기존처럼 중단합니다. close-check는 실제 시작/확인 시각과 소요도 반환합니다.

snapshot과 plan의 최상위는 JSON object여야 하며, 다른 형식은 원본을 보존하고 구체 형식 사유와 함께 차단합니다.

`session.py merge-guard DIRECTORY --snapshot SNAPSHOT --plan PLAN`은 판단 전에 원본을 새 파일로
보존합니다. plan에는 sha·author·checks를, snapshot에는 PR 메타데이터·전체 CI와 threads
(nodes/pageInfo)를 넣습니다. 실패 결과에는 HEAD_CHANGED·MERGE_STATE·APPROVAL·CHECK_RESULT
등 조건별 실제/기대값과 원본 hash가 남습니다. 성공해도 승인/병합은 수행하지 않으며 별도의
기존 승인과 정확 head를 지정한 일반 병합이 필요합니다. 과거 실패를 새 성공으로 덮어쓰지 않습니다.


## 필수 마감 확인과 게시의 겹침

마감의 desktop-finish와 output-report --refresh는 모두 유지합니다. `close-check`의 commands에는
실제 호출한 명령별 wall·Python/자식 CPU·원본 stdout/stderr hash를 남깁니다. 이 wall에는
관측 수집·디스크·스케줄링이 섞여 있으므로 전부 순수 연산 또는 불필요한 시간으로 해석하지 않습니다.
이미 결과가 확정된 도구 PR의 게시·정리는 실제 업무 CI가 실행 중일 때 끝내고, 해당 실제 PR의
최종 성공 결과는 CI 종료 후 게시합니다. 고정된 소스/검사 정의는 바꾸지 않으며 총 시간과 CI 뒤
시간을 함께 비교해 단순히 다른 단계로 옮긴 시간을 단축으로 계산하지 않습니다.

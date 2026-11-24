#!/usr/bin/env bash
# .env의 비밀값 한 개를 화면·셸 기록·명령 인자에 남기지 않고 넣거나 바꾼다.
# 사용: nas/scripts/set-env-secret.sh <env-file> <NAME>
#   입력은 화면에 보이지 않는다. Google 앱 비밀번호처럼 띄어쓰기가 있는 값은 공백을 지운다.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <env-file> <NAME>" >&2
  exit 2
fi
env_file="$1"
name="$2"
case "${name}" in
  *[!A-Z0-9_]* | "") echo "invalid variable name: ${name}" >&2; exit 2 ;;
esac
if [ ! -f "${env_file}" ]; then
  echo "missing ${env_file}" >&2
  exit 1
fi

IFS= read -rs -p "${name} 값 입력(화면에 보이지 않음): " value
echo
value="$(printf '%s' "${value}" | tr -d '[:space:]')"
if [ -z "${value}" ]; then
  echo "빈 값이라 바꾸지 않았습니다." >&2
  exit 1
fi

umask 077
tmp="$(mktemp "${env_file}.XXXXXX")"
grep -v "^${name}=" "${env_file}" >"${tmp}" || true
printf '%s=%s\n' "${name}" "${value}" >>"${tmp}"
chmod 600 "${tmp}"
mv "${tmp}" "${env_file}"
unset value
echo "${name}을(를) ${env_file}에 저장했습니다. 값은 출력하지 않습니다."

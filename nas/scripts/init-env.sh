#!/usr/bin/env bash
# NAS 개발 환경의 .env를 처음 한 번 만든다. 값은 화면에 출력하지 않는다.
# 사용: nas/scripts/init-env.sh <runtime-dir> <server-src> <ai-src> <model19-dir> <model-version>
set -euo pipefail

if [ "$#" -ne 5 ]; then
  echo "usage: $0 <runtime-dir> <server-src> <ai-src> <model19-dir> <model-version>" >&2
  exit 2
fi

runtime_dir="$1"
env_file="${runtime_dir}/.env"

if [ -e "${env_file}" ]; then
  echo "${env_file} already exists; refusing to overwrite generated credentials" >&2
  exit 1
fi

for path in "$2" "$3" "$4"; do
  if [ ! -d "${path}" ]; then
    echo "missing directory: ${path}" >&2
    exit 1
  fi
done
if [ ! -f "$4/manifest.json" ]; then
  echo "model directory has no manifest.json: $4" >&2
  exit 1
fi

token() { openssl rand -hex 24; }

umask 077
mkdir -p "${runtime_dir}"
{
  echo "# generated $(date -u +%Y-%m-%dT%H:%M:%SZ); do not commit or print"
  echo "IPGO_SERVER_SRC=$2"
  echo "IPGO_AI_SRC=$3"
  echo "IPGO_MODEL19_HOST_DIR=$4"
  echo "IPGO_ENGINE_MODEL_VERSION=$5"
  echo "POSTGRES_ADMIN_PASSWORD=$(token)"
  echo "IPGO_MIGRATOR_PASSWORD=$(token)"
  echo "IPGO_SERVER_PASSWORD=$(token)"
  echo "IPGO_AI_READER_PASSWORD=$(token)"
  echo "IPGO_AI_SERVICE_READER_PASSWORD=$(token)"
  echo "IPGO_JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')"
  echo "IPGO_AUTH_COOKIE_SECURE=false"
  echo "IPGO_SERVER_PORT=18090"
} >"${env_file}"
chmod 600 "${env_file}"
echo "created ${env_file} (mode 600)"

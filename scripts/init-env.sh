#!/bin/sh
# Run from the installation directory. Requires only OpenSSL and POSIX tools.
set -eu
umask 077
init_target=.env
init_template=.env.example
while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file|--template)
      [ "$#" -ge 2 ] || { printf '%s\n' '옵션 뒤에 파일 경로를 지정하세요.' >&2; exit 1; }
      if [ "$1" = --env-file ]; then init_target=$2; else init_template=$2; fi
      shift 2 ;;
    --help)
      printf '%s\n' 'Usage: sh init-env.sh [--env-file PATH] [--template PATH]'
      exit 0 ;;
    *) printf '%s\n' '알 수 없는 옵션입니다.' >&2; exit 1 ;;
  esac
done
command -v openssl >/dev/null 2>&1 || {
  printf '%s\n' 'OpenSSL이 필요합니다. 설치 후 다시 실행하세요.' >&2
  exit 1
}
mkdir -p "$(dirname "$init_target")"
init_lock=${init_target}.init.lock
init_tmp=
init_next=

if [ -L "$init_target" ] || { [ -e "$init_target" ] && [ ! -f "$init_target" ]; }; then
  printf '%s\n' '.env는 일반 파일이어야 합니다.' >&2
  exit 1
fi
if ! mkdir "$init_lock" 2>/dev/null; then
  printf '%s\n' '다른 환경 설정 작업이 실행 중입니다. 완료 후 다시 시도하세요.' >&2
  exit 1
fi
trap 'rm -f "$init_tmp" "$init_next"; rmdir "$init_lock"' 0
trap 'exit 1' 1 2 15

if [ -f "$init_target" ]; then
  init_source=$init_target
elif [ -f "$init_template" ]; then
  init_source=$init_template
else
  printf '%s\n' '.env.example을 먼저 내려받으세요.' >&2
  exit 1
fi

init_tmp=$(mktemp "${init_target}.init.XXXXXX")
cat "$init_source" > "$init_tmp"

for init_key in POSTGRES_PASSWORD ADMIN_SETUP_CODE AUTH_ENCRYPTION_KEY S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY GARAGE_RPC_SECRET; do
  # Inspect only whether the final assignment is blank; never evaluate dotenv as shell.
  init_present=$(awk -v key="$init_key" '
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {
      value=$0
      sub("^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=", "", value)
      sub(/[[:space:]]+#.*$/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      present=(value!="" && value!="\"\"" && value!="\047\047")
    }
    END { print present ? "yes" : "no" }
  ' "$init_tmp")
  [ "$init_present" = yes ] && continue

  case "$init_key" in
    AUTH_ENCRYPTION_KEY) init_value=$(openssl rand -base64 32 | tr '+/' '-_') ;;
    S3_ACCESS_KEY_ID) init_value=GK$(openssl rand -hex 16) ;;
    *) init_value=$(openssl rand -hex 32) ;;
  esac
  [ -n "$init_value" ] || { printf '%s\n' '시크릿 생성에 실패했습니다.' >&2; exit 1; }

  init_next=$(mktemp "${init_target}.init.XXXXXX")
  awk -v key="$init_key" -v replacement="$init_value" '
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" { print key "=" replacement; found=1; next }
    { print }
    END { if (!found) print key "=" replacement }
  ' "$init_tmp" > "$init_next"
  mv "$init_next" "$init_tmp"
  init_next=
done

if [ -f "$init_target" ] && cmp -s "$init_tmp" "$init_target"; then
  chmod 600 "$init_target"
else
  mv "$init_tmp" "$init_target"
fi
printf '%s\n' '환경 설정 준비 완료: 기존 값은 유지하고 비어 있는 시크릿만 생성했습니다.'
printf '%s\n' '최초 관리자 설정 코드는 지정한 환경 파일의 ADMIN_SETUP_CODE에서 확인하세요.'

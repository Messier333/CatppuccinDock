# 개발·검증·배포 전 확인

[프로젝트 소개·실행](../README.md)

## 개발과 검증

```bash
sh scripts/init-env.sh
docker compose -f docker-compose.yml -f compose.build.yml up -d database
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001 --env-file ../.env
```

프런트는 `frontend/`에서 `npm ci` 후 `npm run dev`로 실행합니다. `/api` 요청은 기본적으로 `http://127.0.0.1:8001`로 전달합니다. 변경한 배포 환경변수도 로컬 백엔드에 제공하세요.

```bash
docker build --target test -t catppuccindock-auth-test backend
docker run --rm catppuccindock-auth-test
```

테스트는 별도 SQLite DB와 로컬 임시 OIDC 서버를 사용하며 운영 DB를 사용하지 않습니다. 로그인·권한·사용자 간 데이터 격리·CRUD·2FA·기존 계정 이전·실제 RSA 서명 토큰 및 PKCE·정렬·검색 제안 검증을 포함합니다.

프런트 전체 로직 테스트: `cd frontend && npm test`.

작업 흐름은 `feat/*`·`fix/*` → `dev` → `main`입니다. 작업 브랜치는 `dev`에서 만들고 PR의 대상도 `dev`로 지정합니다. 여러 변경을 `dev`에 모은 다음 출시할 때 `dev` → `main` PR을 만듭니다.

GitHub Actions는 `dev` 푸시와 `dev`·`main` 대상 PR에서 품질·보안·앱·브라우저 검증을 실행합니다. `dev`는 검증만 하며, 새 푸시가 들어오면 이전 `dev` 검증을 취소하고 최신 변경을 검사합니다. `dev`의 **Run workflow** 수동 실행도 검증만 합니다. PR을 `main`에 머지하면 테스트 성공 후 patch 버전 태그를 자동 생성하고 GHCR 이미지와 GitHub 릴리즈를 게시합니다. 직접 만든 버전 태그도 지원합니다. 워크플로와 이미지 실행 방법은 [컨테이너 빌드·배포](containers.md)를 참고하세요.

`main`에 워크플로 변경을 반영한 후 GitHub의 브랜치 생성 화면에서 **Source: main**, **New branch name: dev**로 통합 브랜치를 만드세요. 기존 작업 PR은 대상 브랜치를 `dev`로 변경할 수 있습니다. `main`에서 직접 수정한 내용이 있으면 다음 작업 전에 `main` → `dev` PR로 동기화합니다.

API 계약은 [docs/api.md](api.md)를 참고하세요. 배포 전에는 DB·`.env`·Garage의 메타데이터/데이터 볼륨을 함께 백업하세요. [스토리지 운영 안내](storage.md)에 이관·백업 절차가 있습니다. 로컬 백업 디렉터리 `.local-backups/`는 버전 관리에서 제외됩니다.

## 코드 품질 검사

프로젝트 루트에서 실행합니다. 개발용 린터는 앱 런타임 의존성과 분리했습니다.

```bash
python3 -m pip install -r requirements-lint.txt
ruff check backend scripts
npm --prefix frontend ci
npm --prefix frontend run lint
```

Python은 [ruff.toml](../ruff.toml)의 Ruff 규칙으로 문법 오류·정의되지 않은 이름·잘못된 구문·사용하지 않는 import를 검사합니다. JavaScript·Vue·서비스 워커·프론트 테스트는 [ESLint 설정](../frontend/eslint.config.js)의 권장 오류 규칙과 Vue essential 규칙을 적용합니다. 의도적으로 사용하지 않는 인자는 `_`로 시작하며, 규칙 예외는 필요한 줄에 이유를 명시합니다.

GitHub Actions 파일은 actionlint와 실행기의 ShellCheck로 구문·표현식·재사용 워크플로 호출·셸 단계를 검사합니다. 로컬에서도 [공식 설치 방법](https://github.com/rhysd/actionlint/blob/main/docs/install.md)에 따라 actionlint 1.7.12와 ShellCheck를 설치한 뒤 실행할 수 있습니다.

```bash
actionlint
```

CI의 [quality.yml](../.github/workflows/quality.yml)은 세 검사를 병렬로 실행합니다. 하나라도 실패하면 테스트·이미지 게시·릴리즈 단계가 진행되지 않습니다. Ruff는 개발용 요구사항에, ESLint는 npm 잠금 파일에 버전을 고정합니다. actionlint 배포 파일은 고정 버전과 SHA-256을 확인한 후 실행합니다.

## Git에 올리기 전 확인

```bash
python3 scripts/check_publish.py
```

공개할 소스·제외할 실행 데이터와 검사한 소스만 담은 압축본 생성 방법은 [GitHub 공개 준비](publishing.md)에 정리했습니다. 실제 비밀값은 `.env`와 운영 DB에만 보관하며 예시 파일은 빈 비밀값을 사용합니다. 이 검사는 현재 파일을 대상으로 하며 Git 이력이나 외부 서비스의 데이터는 검사하지 않습니다.

자동완성 연동 참고: [DuckDuckGo 공식 Suggest URL](https://duckduckgo.com/duckduckgo-help-pages/get-duckduckgo/deploy-duckduckgo), [SearXNG의 Yandex 연동 코드](https://docs.searxng.org/_modules/searx/autocomplete.html#yandex).


## 로컬 생성 파일

`.editorconfig`는 UTF-8·LF와 파일별 들여쓰기 기준을, `.gitattributes`는 소스 줄바꿈과 바이너리 리소스 구분을 지정합니다. 기존 소스 전체를 일괄 재포맷하지는 않습니다.

`frontend/dist/`, Python의 `__pycache__/`와 `.pyc`, 테스트 리포트·인증 상태 파일·임시 파일은 소스가 아닙니다. 의존성은 `frontend/node_modules/`와 `backend/.venv/`에 로컬로 유지하되 Git/Docker 빌드 컨텍스트에서 제외합니다. 프런트 Docker 컨텍스트에는 소스·공개 리소스·빌드 입력·라이선스만, 백엔드 컨텍스트에는 앱·테스트·빌드 입력만 포함합니다.

평문 `*.sql` 덤프도 기본 제외합니다. SQL 마이그레이션 소스가 필요하면 `backend/app/db/` 아래에 두면 포함됩니다. `.env.example`과 `*.env.example` 템플릿은 포함되지만 실제 `.env`·`production.env`·`.envrc`는 제외합니다. 브라우저 테스트의 인증 상태 JSON·HAR·리포트도 제외합니다. 운영 데이터·로그·백업은 삭제하지 않고 별도 보관합니다.

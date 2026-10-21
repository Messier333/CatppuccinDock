# 컨테이너 빌드·배포

[프로젝트 소개](../README.md)

## 빠른 설치

Docker Engine·Docker Compose V2 2.23.1 이상·OpenSSL·wget이 필요합니다. [README의 명령어](../README.md#빠른-설치)를 복사해 실행하면 Compose 파일과 환경변수 예시를 다운로드하고 여섯 키를 생성한 뒤 서비스를 시작합니다. 별도의 설치 스크립트를 내려받을 필요가 없습니다.

접속은 `http://서버주소:8090/`이며, 최초 관리자 설정에 `.env`의 `ADMIN_SETUP_CODE`를 사용합니다. 선택한 이미지가 GHCR에 게시되어 있어야 하며 비공개 패키지는 먼저 로그인해야 합니다.

`docker-compose.yml`에는 로컬 빌드가 없고 Garage 설정도 내장되어 있습니다. 별도 소스·Python·설정 파일 다운로드 없이 네 서비스를 기동하며 DB·스토리지 볼륨과 로그 디렉터리는 자동 생성합니다. DB·Garage 포트는 내부 네트워크에서 사용하고 포털 포트만 외부에 공개합니다.

빠른 설치는 `IMAGE_TAG=latest`로 실행합니다. 특정 릴리즈 버전을 고정하고 싶을 때만 해당 릴리즈의 ‘직접 설정해서 배포’ 안내나 첨부 파일을 사용하세요. 첨부된 환경변수 예시에만 해당 버전이 지정되어 있습니다.

## 직접 설정해서 배포

빠른 설치의 자동 키 생성 대신 설정을 직접 작성할 수도 있습니다.

```bash
mkdir -p ~/catppuccindock && cd ~/catppuccindock
umask 077
wget -O docker-compose.yml https://raw.githubusercontent.com/overture-1928/CatppuccinDock/main/docker-compose.yml
test -f .env || wget -O .env https://raw.githubusercontent.com/overture-1928/CatppuccinDock/main/.env.example
chmod 600 .env
${EDITOR:-vi} .env
```

아래 여섯 시크릿을 모두 채우고 원하는 포트·버전을 지정합니다. [키별 생성 명령과 형식](secrets.md#저장할-시크릿)을 참고하세요.

| 환경변수 | 용도 |
| --- | --- |
| `POSTGRES_PASSWORD` | PostgreSQL 비밀번호 |
| `ADMIN_SETUP_CODE` | 최초 관리자 생성 코드 |
| `AUTH_ENCRYPTION_KEY` | 2FA·OIDC·API 인증정보 암호화 키 |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Garage 전용 S3 인증정보 |
| `GARAGE_RPC_SECRET` | Garage 노드 통신 키 |
| `PORTAL_PORT` | 포털 포트, 기본 8090 |
| `COOKIE_SECURE` | HTTPS 서비스 시 true |
| `GHCR_IMAGE_PREFIX` | 기본 ghcr.io/overture-1928/catppuccindock |
| `IMAGE_TAG` | 기본 latest; 정식 버전은 1.0.0처럼 지정 |

```bash
docker compose pull
docker compose up -d
docker compose ps
```

이미지만 먼저 직접 받는 것도 가능합니다. 아래 예시는 `.env`에 `IMAGE_TAG=1.0.0`을 지정한 경우입니다. Compose가 앱 이미지와 DB·Garage를 연결합니다.

```bash
docker pull ghcr.io/overture-1928/catppuccindock-frontend:1.0.0
docker pull ghcr.io/overture-1928/catppuccindock-backend:1.0.0
docker compose up -d
```

준비 완료까지 기다리려면 `docker compose up -d --wait`를 사용합니다. Garage 설정 예시는 `deploy/garage/garage.toml`에 있지만 기본 설치는 Compose 안의 설정을 사용합니다.

NPG·NPM 등 프록시 뒤에서 로그인 실패 IP를 기록하려면 신뢰할 프록시 설정을 `deploy/nginx/trusted-proxies/*.conf`에 두고 프론트를 재시작합니다. [실제 IP·Fail2ban 설정](authentication.md#로그인-실패-로그와-fail2ban)

## Infisical 등 시크릿 저장소

같은 여섯 시크릿을 Infisical에 등록하고 CLI로 주입하면 `.env` 없이 동일한 Compose 파일을 실행할 수 있습니다. 호스트 CLI 설치·인증과 시크릿 등록을 먼저 진행하세요.

```bash
infisical sm run --projectId '<PROJECT_ID>' --env prod -- \
  docker compose --env-file /dev/null up -d
```

`--env-file /dev/null`은 로컬 dotenv 로드를 끄고 주입된 환경변수를 사용하도록 합니다. 이미지 버전·포트·HTTPS 설정도 저장소에서 제공할 수 있습니다. [Infisical 설정·업데이트·다른 저장소 사용](secrets.md)

## 이미지와 업데이트

기본 이미지 주소는 다음과 같습니다.

```text
ghcr.io/overture-1928/catppuccindock-frontend
ghcr.io/overture-1928/catppuccindock-backend
```

`latest`는 main의 테스트를 통과한 이미지입니다. 일반 업데이트는 설치 명령을 반복하지 않고 기존 디렉터리에서 다음 명령만 실행합니다. `IMAGE_TAG=latest`는 그대로 두고 새 이미지를 받습니다.

```bash
cd ~/catppuccindock
docker compose pull backend frontend
docker compose up -d
docker compose ps
```

새 이미지는 `pull`로 받아야 적용됩니다. 비밀번호·암호화 키 생성이나 최초 관리자 설정을 다시 할 필요가 없습니다. 특정 버전을 고정할 때만 `.env`의 `IMAGE_TAG`를 원하는 버전으로 변경합니다.

프론트·백엔드에 같은 태그를 적용하며 `sha-<40자리 SHA>`로 커밋을 지정할 수도 있습니다. 포크는 `GHCR_IMAGE_PREFIX`를 소문자 소유자/저장소 이름으로 변경합니다. Infisical 사용 시 저장소의 버전을 변경하고 위 두 명령에 각각 CLI 주입을 적용합니다.

기존 설치에서 업데이트할 때는 시크릿·암호화 키를 유지하고 DB·Garage를 함께 백업합니다. 동일한 Compose 프로젝트 이름을 사용하면 기존 볼륨을 재사용합니다. Compose 구성이 바뀐 릴리즈에서만 새 파일을 받아 별도로 지정한 설정과 비교해 반영합니다. `.env`는 다시 내려받거나 덮어쓰지 않습니다. [스토리지 백업](storage.md)

앱 업데이트 명령은 DB·Garage 엔진을 새 버전으로 바꾸지 않습니다. 엔진 갱신은 [DB·Garage 업데이트](storage.md#dbgarage-업데이트)에서 패치·메이저 변경을 구분해 진행합니다.

### GitHub 계정명 변경 후 기존 설치

기존 `.env` 또는 Infisical에 이미지 경로를 직접 등록한 경우 `GHCR_IMAGE_PREFIX=ghcr.io/overture-1928/catppuccindock`으로 변경하고 기존 비밀번호·암호화 키는 유지합니다. 새 기본 설정과 Actions는 변경된 저장소 소유자를 사용합니다. 원격 주소는 `https://github.com/overture-1928/CatppuccinDock.git`입니다.

## 소스에서 빌드·개발

저장소를 복제하고 위와 같이 `.env`를 준비한 뒤 로컬 빌드용 덮어쓰기를 사용합니다. 개발 환경에서는 `sh scripts/init-env.sh`로 빈 시크릿을 채우는 내부 도구도 사용할 수 있습니다.

```bash
git clone https://github.com/overture-1928/CatppuccinDock.git
cd CatppuccinDock
sh scripts/init-env.sh
docker compose -f docker-compose.yml -f compose.build.yml up --build -d --wait
```

이 구성은 로컬 소스에서 두 앱 이미지를 빌드하고 개발 도구용 DB 포트를 127.0.0.1:5432에 엽니다. 기본 이미지 설치에서는 이 파일을 사용하지 않습니다. 이전의 `scripts/setup_storage.py`는 기존 운영자를 위한 스토리지 키 설정 도구로 유지합니다.

## GitHub Actions·GHCR 공개 설정

[containers.yml](../.github/workflows/containers.yml)은 실행 조건과 순서만 관리하며, 역할별 재사용 워크플로를 호출합니다.

| 파일 | 역할 |
| --- | --- |
| [containers.yml](../.github/workflows/containers.yml) | PR·main·태그 이벤트 수신, 품질 검사 → 테스트 → 이미지 게시 → 릴리즈 순서 관리 |
| [quality.yml](../.github/workflows/quality.yml) | Ruff·ESLint·actionlint 검사를 병렬 실행 |
| [checks.yml](../.github/workflows/checks.yml) | 설정 검사·프론트·백엔드 테스트를 서로 독립된 세 작업으로 병렬 실행 |
| [publish-images.yml](../.github/workflows/publish-images.yml) | AMD64·ARM64 프론트·백엔드 이미지를 GHCR에 게시 |
| [release.yml](../.github/workflows/release.yml) | 버전별 배포 파일·본문 준비, GitHub 릴리즈 생성 |

검증에는 공개 파일 검사·시크릿 초기화/릴리즈 파일 테스트·Compose 검증·프론트 테스트와 이미지 빌드·별도 SQLite DB의 백엔드 테스트가 포함됩니다. 코드 품질 검사와 세 검증 작업이 모두 통과해야 이미지를 게시하고, 두 이미지 게시가 모두 성공해야 태그의 릴리즈를 생성합니다.

재사용 파일은 `workflow_call`로만 실행합니다. 같은 커밋의 파일과 실행 컨텍스트를 공유하고, 별도 `workflow_run`으로 연결하지 않아 main·태그·PR의 결과가 섞이지 않습니다. 동시 실행 관리는 진입점에만 둡니다. [GitHub 재사용 워크플로 안내](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)

| 실행 조건 | 이미지 태그·릴리즈 |
| --- | --- |
| main 푸시·수동 실행 | latest, main, sha-커밋; 릴리즈 생성 없음 |
| v1.2.3 태그 푸시 | 1.2.3, 1.2, sha-커밋; 두 이미지 성공 후 릴리즈 생성 |
| PR | 검증만 실행 |

태그 빌드는 Docker의 latest 태그를 바꾸지 않습니다. 정식 GitHub 릴리즈는 Latest로 지정하고 사전 릴리즈는 따로 표시합니다. Action은 커밋 SHA로 고정하며 Dependabot이 갱신을 제안합니다.

Actions는 GitHub의 `GITHUB_TOKEN`으로 인증합니다. 검증은 읽기 권한, 이미지 게시에는 `packages: write`, 릴리즈 생성에는 `contents: write`만 부여합니다. 실제 서버의 시크릿은 Actions에 등록하지 않습니다. [GitHub 이미지 게시 안내](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)

처음 이미지를 게시한 뒤 GitHub의 Packages에서 프론트·백엔드 각각을 **Public**으로 설정하면 서버에서 로그인 없이 받을 수 있습니다. 처음 생성된 패키지의 기본 공개 범위는 비공개입니다. 비공개 운영은 `read:packages` 권한 PAT classic으로 `docker login ghcr.io`를 먼저 실행하세요. [GHCR 안내](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

## 버전 릴리즈 만들기

변경사항을 main에 커밋·푸시한 뒤 태그를 만듭니다.

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

릴리즈에는 [.github/release-notes.md](../.github/release-notes.md)의 빠른 설치·직접 설정·Infisical 배포·업데이트 안내와 자동 변경 내역이 들어갑니다. 병합 PR·기여자·전체 비교 링크는 GitHub가 생성합니다. [자동 릴리즈 노트](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)

Assets에는 `docker-compose.yml`, `.env.example`, 두 파일과 `DEPLOY.md`를 묶은 `CatppuccinDock-v1.0.0-deploy.tar.gz`, 체크섬 `SHA256SUMS`가 첨부됩니다. 환경변수 예시는 해당 릴리즈 이미지에 고정되어 있으며 실제 키나 운영 데이터는 포함하지 않습니다.

같은 태그의 릴리즈가 이미 있으면 재실행해도 본문을 덮어쓰지 않습니다. `v1.1.0-rc.1`은 사전 릴리즈로 표시하며 Latest로 지정하지 않습니다. 두 이미지 게시가 하나라도 실패하면 릴리즈를 만들지 않습니다.

[prepare_release.py](../scripts/prepare_release.py)로 실제 게시 없이 결과를 확인할 수 있습니다. 새 출력 폴더를 지정하세요.

```bash
python3 scripts/prepare_release.py --tag v1.0.0 --repository overture-1928/CatppuccinDock --output /tmp/catppuccindock-release-preview
```

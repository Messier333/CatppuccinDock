CatppuccinDock **@@TAG@@** · AMD64 / ARM64

## Docker 이미지

| 서비스 | 이미지 |
| --- | --- |
| 프론트엔드 | `@@IMAGE_PREFIX@@-frontend:@@VERSION@@` |
| 백엔드 | `@@IMAGE_PREFIX@@-backend:@@VERSION@@` |

Docker Engine, **Docker Compose V2 2.23.1 이상**, OpenSSL과 wget이 필요합니다. 기본 Compose가 PostgreSQL·Garage·백엔드·프론트엔드를 함께 실행합니다.

## 빠른 설치

```bash
# 설치 디렉터리 생성
mkdir -p ~/catppuccindock && cd ~/catppuccindock
umask 077

# 필수 파일 다운로드 (.env가 이미 있으면 보존)
wget -O docker-compose.yml https://github.com/@@REPOSITORY@@/releases/download/@@TAG@@/docker-compose.yml
test -f .env || wget -O .env https://github.com/@@REPOSITORY@@/releases/download/@@TAG@@/.env.example

# 비어 있는 시크릿만 생성 (기존 값은 유지)
for dock_key in POSTGRES_PASSWORD ADMIN_SETUP_CODE S3_SECRET_ACCESS_KEY GARAGE_RPC_SECRET; do
  sed -i "s|^${dock_key}=$|${dock_key}=$(openssl rand -hex 32)|" .env
done
sed -i "s|^AUTH_ENCRYPTION_KEY=$|AUTH_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')|" .env
sed -i "s|^S3_ACCESS_KEY_ID=$|S3_ACCESS_KEY_ID=GK$(openssl rand -hex 16)|" .env
chmod 600 .env

# 서비스 시작
docker compose up -d
```

접속: **http://서버주소:8090/**

처음 접속하면 `.env`의 `ADMIN_SETUP_CODE`로 관리자 계정을 만듭니다. 다운로드한 환경변수 예시는 이 릴리즈의 이미지 버전에 고정되어 있으며 실제 키는 위 명령으로 서버에서 생성합니다. 설치용 쉘 스크립트나 소스 복제는 필요하지 않습니다.

- 포트 변경: `.env`의 `PORTAL_PORT`(기본 8090)
- HTTPS 리버스 프록시: `COOKIE_SECURE=true`
- DB·Garage 데이터: Docker 볼륨에 저장
- GHCR 패키지가 비공개인 경우: `read:packages` 토큰으로 먼저 `docker login ghcr.io` 실행

Assets의 `@@ASSET@@`에도 Compose·환경변수 예시·이 안내(`DEPLOY.md`)가 들어 있습니다. 묶음을 풀어 설치한다면 `umask 077; cp -n .env.example .env`로 환경 파일을 준비하고 위 시크릿 생성·서비스 시작 명령을 실행하세요.

## 직접 설정해서 배포

자동 생성 명령 대신 환경변수 예시를 `.env`로 내려받아 값을 직접 작성할 수도 있습니다. 위 설치 명령과 별도로 진행하는 방법입니다.

```bash
mkdir -p ~/catppuccindock && cd ~/catppuccindock
umask 077
wget -O docker-compose.yml https://github.com/@@REPOSITORY@@/releases/download/@@TAG@@/docker-compose.yml
test -f .env || wget -O .env https://github.com/@@REPOSITORY@@/releases/download/@@TAG@@/.env.example
chmod 600 .env
${EDITOR:-vi} .env
```

`POSTGRES_PASSWORD`, `ADMIN_SETUP_CODE`, `AUTH_ENCRYPTION_KEY`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `GARAGE_RPC_SECRET`를 모두 채웁니다. [키별 생성 형식](https://github.com/@@REPOSITORY@@/blob/@@TAG@@/docs/secrets.md#저장할-시크릿)을 참고하세요. 파일 준비 후 이미지를 직접 받고 Compose로 실행합니다.

```bash
docker pull @@IMAGE_PREFIX@@-frontend:@@VERSION@@
docker pull @@IMAGE_PREFIX@@-backend:@@VERSION@@
docker compose up -d
docker compose ps
```

## Infisical 등 시크릿 저장소로 배포

`.env` 없이도 같은 Compose 파일을 사용할 수 있습니다. 호스트에 [Infisical CLI](https://infisical.com/docs/cli/overview)를 설치하고 위 여섯 시크릿을 프로젝트의 `prod` 환경에 등록합니다. `GHCR_IMAGE_PREFIX=@@IMAGE_PREFIX@@`, `IMAGE_TAG=@@VERSION@@`도 함께 등록해 이 버전을 선택하세요.

```bash
mkdir -p ~/catppuccindock && cd ~/catppuccindock
wget -O docker-compose.yml https://github.com/@@REPOSITORY@@/releases/download/@@TAG@@/docker-compose.yml
infisical login
infisical sm run --projectId '<PROJECT_ID>' --env prod -- \
  docker compose --env-file /dev/null up -d
```

Infisical이 실행 환경변수로 주입하며 로컬 `.env`는 읽거나 만들지 않습니다. 다른 저장소도 같은 이름의 환경변수를 주입하면 사용할 수 있습니다. [인증·업데이트·시크릿 저장소 설정](https://github.com/@@REPOSITORY@@/blob/@@TAG@@/docs/secrets.md)

## 기존 설치 업데이트

기존 설치 디렉터리에서 DB·시크릿·Garage를 백업한 뒤 이미지 설정만 아래 값으로 변경합니다. 비밀번호·암호화 키는 유지합니다.

```dotenv
GHCR_IMAGE_PREFIX=@@IMAGE_PREFIX@@
IMAGE_TAG=@@VERSION@@
```

```bash
docker compose pull backend frontend
docker compose up -d
docker compose ps
```

Infisical 사용 시 저장소의 이미지 설정을 변경하고 각 Compose 명령을 `infisical sm run … -- docker compose --env-file /dev/null …`로 실행하세요. Compose 구성을 갱신할 때는 기존 파일과 비교합니다. 같은 디렉터리·Compose 프로젝트 이름을 사용하면 기존 데이터 볼륨을 계속 사용합니다.

[전체 배포 안내](https://github.com/@@REPOSITORY@@/blob/@@TAG@@/docs/containers.md) · [백업·스토리지 운영](https://github.com/@@REPOSITORY@@/blob/@@TAG@@/docs/storage.md)

---

## 변경 내역


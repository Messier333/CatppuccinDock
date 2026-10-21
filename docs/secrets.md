# .env와 외부 시크릿 저장소

[프로젝트 소개](../README.md) · [컨테이너 배포](containers.md)

## 기본: .env

[빠른 설치](../README.md#빠른-설치)는 Compose 파일과 환경변수 예시를 다운로드하고 OpenSSL로 키를 생성한 뒤 `docker compose up -d`를 실행합니다. 별도 설치 스크립트는 필요하지 않습니다. `.env`는 설치 디렉터리에 600 권한으로 보관합니다. 문서의 생성 명령은 값이 비어 있는 줄만 채우므로 재실행해도 기존 키를 유지합니다.

직접 값을 설정하려면 환경변수 예시를 `.env`로 복사하고 아래 형식에 맞춰 여섯 키를 채웁니다. [직접 배포 절차](containers.md#직접-설정해서-배포)

## Infisical: .env 없이 실행

동일한 Compose 파일이 프로세스 환경변수도 읽으므로 앱 이미지나 Compose 설정을 바꿀 필요가 없습니다. Infisical CLI로 시크릿을 주입하고 `--env-file /dev/null`로 로컬 dotenv 자동 로드를 끕니다. 시크릿은 실행 중인 컨테이너의 환경변수로 전달됩니다.

호스트에 [Infisical CLI](https://infisical.com/docs/cli/overview)를 설치하고 프로젝트·환경과 로그인 또는 머신 인증을 준비합니다. 아래 명령은 현재 CLI의 `infisical sm run` 기준입니다. [공식 런타임 주입 안내](https://infisical.com/docs/integrations/platforms/docker)

### 저장할 시크릿

Infisical의 해당 프로젝트·환경에 아래 여섯 이름을 등록합니다. 이미 운영 중이라면 기존 `.env`의 값을 그대로 옮겨 DB·파일·암호화된 설정을 계속 사용합니다. 기본 `.env` 배포도 동일한 키와 형식을 사용합니다.

| 이름 | 새 설치에서 생성할 값 |
| --- | --- |
| `POSTGRES_PASSWORD` | `openssl rand -hex 32` |
| `ADMIN_SETUP_CODE` | `openssl rand -hex 32` |
| `AUTH_ENCRYPTION_KEY` | `openssl rand -base64 32 \| tr '+/' '-_'` |
| `S3_ACCESS_KEY_ID` | `printf GK; openssl rand -hex 16` |
| `S3_SECRET_ACCESS_KEY` | `openssl rand -hex 32` |
| `GARAGE_RPC_SECRET` | `openssl rand -hex 32` |

각 키는 별도로 생성합니다. 암호화 키는 URL-safe Base64로 인코딩한 32바이트, Garage 접근 키는 `GK` 다음 32자리 16진수, RPC 키는 64자리 16진수입니다.

`PORTAL_PORT`, `COOKIE_SECURE`, `IMAGE_TAG`, `GHCR_IMAGE_PREFIX` 등 실행 설정도 같은 환경에 등록할 수 있으며, 생략하면 Compose의 기본값을 사용합니다. 정식 버전을 고정하려면 `IMAGE_TAG=1.0.0`처럼 지정하세요. HTTPS 서비스는 `COOKIE_SECURE=true`로 설정합니다.

### Compose 직접 실행

```bash
mkdir -p ~/catppuccindock && cd ~/catppuccindock
wget -O docker-compose.yml https://raw.githubusercontent.com/overture-1928/CatppuccinDock/main/docker-compose.yml
infisical login
infisical sm run --projectId '<PROJECT_ID>' --env prod -- \
  docker compose --env-file /dev/null up -d
```

이 방식은 `.env`를 만들지 않습니다. 필수 키가 누락되면 Compose가 실행 전에 오류를 표시합니다. 시크릿은 컨테이너 환경 설정에 남으므로 Docker 접근 권한을 가진 운영자는 조회할 수 있습니다.

셀프 호스팅은 CLI의 `INFISICAL_DOMAIN`을 자신의 서버 주소로 지정합니다. 자동 배포는 CLI의 머신 인증으로 발급받은 `INFISICAL_TOKEN`을 배포 환경에서 제공하며 앱의 Compose 파일이나 이미지에는 넣지 않습니다. CLI 인증·토큰 보관은 Infisical에서 관리합니다.

### 업데이트와 키 변경

컨테이너를 새로 만들 때에도 동일한 시크릿을 주입합니다.

```bash
infisical sm run --projectId '<PROJECT_ID>' --env prod -- \
  docker compose --env-file /dev/null pull backend frontend
infisical sm run --projectId '<PROJECT_ID>' --env prod -- \
  docker compose --env-file /dev/null up -d
```

이미 기동한 컨테이너는 저장소의 값 변경을 실시간으로 다시 읽지 않습니다. 값을 바꾸어 적용하려면 시크릿을 다시 주입하여 컨테이너를 재생성해야 합니다. DB 비밀번호·S3 키·암호화 키는 저장소 값만 임의로 바꾸지 않고 각 서비스의 키 변경·데이터 이전 절차와 함께 관리합니다.

다른 시크릿 저장소도 같은 여섯 이름을 프로세스 환경변수로 주입할 수 있으면 동일한 방식으로 실행할 수 있습니다. [Compose 환경변수](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

## 설치 디렉터리 밖의 환경 파일

외부 저장소 대신 별도 경로에 파일을 보관해도 됩니다. 기존 값을 보존해 600 권한의 파일을 준비하고, 실행·업데이트 시 같은 경로를 지정하세요.

```bash
docker compose --env-file /안전한/경로/catppuccindock.env up -d
```

서버 전체 백업에는 DB·Garage와 함께 환경 파일 또는 시크릿 저장소의 복구 방법도 포함합니다. `AUTH_ENCRYPTION_KEY`를 잃으면 기존 2FA·OIDC·API 인증정보를 복호화할 수 없습니다.

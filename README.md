# CatppuccinDock

Catppuccin 테마의 개인 포털입니다. Vue·FastAPI·PostgreSQL·Garage를 Docker Compose로 실행하며, 기본 접속 포트는 **8090**입니다.

- 사용자별 북마크·카테고리·즐겨찾기·최근 사용과 드래그 정렬
- 비밀번호 로그인·2FA·OIDC SSO·로그인 기기 관리·관리자/일반 사용자 권한
- GIF 배경 검색·업로드와 북마크 아이콘 직접 업로드·Garage 저장
- 프록시 API 링크 가져오기·공개 링크·서비스 상태·모니터링 위젯
- 개인 Proxmox 연동·북마크 상태 요약·드래그 패널 구성·권한별 VM/LXC 제어 ([설정 방법](docs/proxmox.md))
- JSON/암호화 백업·복원과 포털 전용 주소의 PWA 설치

## 빠른 설치

Docker Engine, **Docker Compose V2 2.23.1 이상**, OpenSSL과 wget이 필요합니다. 기본 Compose는 GHCR 이미지를 내려받아 실행하며 Garage 설정·데이터 볼륨도 함께 준비합니다.

```bash
# 설치 디렉터리 생성
mkdir -p ~/catppuccindock && cd ~/catppuccindock
umask 077

# 필수 파일 다운로드 (.env가 이미 있으면 보존)
wget -O docker-compose.yml https://raw.githubusercontent.com/overture-1928/CatppuccinDock/main/docker-compose.yml
test -f .env || wget -O .env https://raw.githubusercontent.com/overture-1928/CatppuccinDock/main/.env.example

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

처음 접속하면 `.env`의 `ADMIN_SETUP_CODE`로 최초 관리자 계정을 만듭니다. 포트는 `PORTAL_PORT`, HTTPS 리버스 프록시는 `COOKIE_SECURE=true`로 설정합니다. 이후 사용자·OIDC·외부 API 연동은 관리자 화면에서 등록합니다.

위 명령은 비어 있는 시크릿만 생성하고 기존 값은 유지합니다. `.env`는 600 권한으로 보관합니다. DB·Garage 데이터는 Docker 볼륨에, 인증 실패 로그는 `logs/auth/`에 보관합니다.

기본 `IMAGE_TAG=latest`는 `main`의 테스트를 통과한 이미지입니다. 특정 정식 버전은 `.env`에 `IMAGE_TAG=1.0.0`처럼 지정하세요. **소유자가 Actions에서 이미지를 게시하고 GHCR 패키지를 Public으로 설정한 뒤** 위 설치 명령을 사용할 수 있습니다. [이미지 게시·공개 설정](docs/containers.md)

## 직접 배포·시크릿 저장소

환경변수를 직접 작성하고 이미지를 내려받아 실행하는 방법은 [직접 배포 안내](docs/containers.md#직접-설정해서-배포)에 있습니다. **Infisical 등 외부 시크릿 저장소도 지원**하며, 동일한 Compose에 환경변수를 주입하면 `.env` 없이 실행할 수 있습니다. [키 등록·CLI 실행 방법](docs/secrets.md)

## 업데이트

최초 설치 명령을 반복할 필요 없이 기존 설치 디렉터리에서 실행합니다. 기본 `IMAGE_TAG=latest`는 그대로 두고 새 이미지를 내려받습니다.

```bash
cd ~/catppuccindock
docker compose pull backend frontend
docker compose up -d
docker compose ps
```

기존 `.env`·비밀번호·암호화 키·데이터 볼륨을 유지합니다. 시크릿 생성 명령은 다시 실행하지 않습니다. 업데이트 전 [DB·Garage 백업](docs/storage.md)을 보관하세요. 특정 버전을 운영할 때만 `.env`의 `IMAGE_TAG`를 원하는 값으로 바꿉니다.

Compose 구성 변경이 안내된 업데이트에서만 새 Compose 파일을 받아 기존 설정과 비교해 반영합니다. Infisical 사용 시에는 [동일한 시크릿 주입을 적용한 업데이트 명령](docs/secrets.md#업데이트와-키-변경)을 사용하세요.

DB·Garage 엔진을 갱신할 때는 [별도의 DB·스토리지 업데이트 절차](docs/storage.md#dbgarage-업데이트)를 따릅니다. PostgreSQL 메이저 변경은 데이터 이전이 필요합니다.

## 소스에서 빌드

저장소를 복제한 환경에서 실행합니다.

```bash
sh scripts/init-env.sh
docker compose -f docker-compose.yml -f compose.build.yml up --build -d --wait
```

## GitHub Actions·릴리즈

`main` 푸시 시 테스트 후 AMD64·ARM64 이미지를 GHCR에 게시합니다. `v1.0.0` 같은 버전 태그에서는 이미지 게시 성공 후 GitHub 릴리즈·변경 내역·배포 안내·첨부 파일을 생성합니다. PR에서는 품질 검사와 검증만 실행합니다. 워크플로는 실행 순서·코드 품질·검증·이미지 게시·릴리즈 파일로 분리하며, 설정 검사·프론트·백엔드 테스트는 병렬로 실행합니다.

Python Ruff·Vue/JavaScript ESLint·Actions actionlint 검사에 실패하면 후속 단계가 차단됩니다. [로컬 품질 검사 방법](docs/development.md#코드-품질-검사)

## 디렉터리

```text
CatppuccinDock/
├── .github/            # 테스트·이미지 게시·릴리즈 템플릿
├── backend/            # FastAPI 소스·테스트
├── frontend/           # Vue 소스·테스트·정적 리소스
├── deploy/             # nginx·fail2ban·Garage 설정 예시
├── docs/               # 사용·인증·연동·API·운영 문서
├── scripts/            # 초기 설정·공개 검사·릴리즈 파일 준비
├── docker-compose.yml  # 이미지를 바로 실행하는 기본 구성
├── compose.build.yml   # 로컬 소스 빌드용 덮어쓰기
└── .env.example        # 실제 .env는 로컬에만 보관
```

## 문서

| 내용 | 문서 |
| --- | --- |
| 북마크·GIF·검색·백업·앱 설치 | [포털 사용 안내](docs/usage.md) |
| 계정·2FA·OIDC·fail2ban | [로그인·보안](docs/authentication.md) |
| 프록시 API·외부 모니터링 | [서비스 연동](docs/integrations.md) |
| 프론트·백엔드 디렉터리와 파일 배치 | [프로젝트 구조](docs/architecture.md) |
| Garage·S3 설정·기존 파일 이관·백업 | [스토리지 운영 안내](docs/storage.md) |
| 로컬 실행·테스트·Git/Docker 제외 규칙 | [개발·배포 전 확인](docs/development.md) |
| .env·Infisical·외부 시크릿 주입 | [시크릿 관리](docs/secrets.md) |
| Actions·GHCR·릴리즈·배포 | [컨테이너 빌드·배포](docs/containers.md) |
| GitHub 공개·제외 규칙·소스 압축본 | [공개 준비](docs/publishing.md) |
| HTTP 요청·응답 계약 | [API](docs/api.md) |

공개 전 프로젝트 루트에서 `python3 scripts/check_publish.py`를 실행하세요. 실제 환경 설정·운영 데이터·로그·백업·의존성·생성 파일은 Git/Docker 빌드 컨텍스트에서 제외합니다. 포함된 원본 라이선스는 [frontend/CATPPUCCIN-STARTPAGE-LICENSE](frontend/CATPPUCCIN-STARTPAGE-LICENSE)에 있습니다.

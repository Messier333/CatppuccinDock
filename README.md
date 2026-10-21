# CatppuccinDock

Catppuccin 테마의 개인 포털입니다. Vue·FastAPI·PostgreSQL·Garage를 Docker Compose로 실행하며, 기본 접속 포트는 **8090**입니다.

- 사용자별 북마크·카테고리·즐겨찾기·최근 사용과 드래그 정렬
- 비밀번호 로그인·2FA·OIDC SSO·관리자/일반 사용자 권한
- GIF 배경 검색·업로드와 북마크 아이콘 직접 업로드·Garage 저장
- 프록시 API 링크 가져오기·공개 링크·서비스 상태·모니터링 위젯
- JSON/암호화 백업·복원과 포털 전용 주소의 PWA 설치

## 실행

```bash
cp .env.example .env
```

처음 실행하기 전에 `.env`에 다음 값을 지정합니다.

- `POSTGRES_PASSWORD`: DB를 처음 만들 때 사용할 비밀번호. 예시 파일은 빈 값이며 반드시 직접 설정해야 합니다. 기존 DB의 비밀번호를 바꾸려면 DB 사용자 비밀번호도 함께 변경해야 합니다.
- `ADMIN_SETUP_CODE`: `python3 -c 'import secrets; print(secrets.token_urlsafe(24))'`로 생성하는 최초 계정 생성 코드.
- `AUTH_ENCRYPTION_KEY`: `python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'`로 생성하는 암호화 키. 2FA 비밀키·OIDC 설정·임시 상태·리버스 프록시 API 토큰을 암호화하므로 배포 때마다 바꾸지 않습니다. DB와 함께 별도로 백업합니다.
- `COOKIE_SECURE`: HTTPS 주소로 서비스하면 `true`. 내부 HTTP 접속은 `false`.

```bash
python3 scripts/setup_storage.py
docker compose up --build -d --wait
```

설정 도구는 `.env`에 없는 Garage 전용 키만 생성합니다. GIF 파일은 비공개 Garage 버킷에, 북마크와 파일 정보는 PostgreSQL에 저장합니다. Garage의 S3·관리 포트는 호스트에 공개하지 않습니다. 기존 DB 파일 이관과 스토리지 백업은 [스토리지 운영 안내](docs/storage.md)를 참고하세요.

- 포털: http://localhost:8090/
- 로그인: http://localhost:8090/login/
- 북마크·계정·관리 설정: http://localhost:8090/admin/
- 상태 확인: http://localhost:8090/api/health

최초 설정 코드와 원하는 아이디·비밀번호(12자 이상)로 첫 관리자 계정을 만듭니다. 그 이후 사용자 계정은 관리자 화면의 **사용자 관리**에서 추가합니다. 모든 포털 화면과 개인 데이터 API는 로그인이 필요합니다.

## 디렉터리

```text
CatppuccinDock/
├── backend/            # FastAPI 소스·테스트
├── frontend/           # Vue 소스·테스트·정적 리소스
├── deploy/             # Garage·nginx·fail2ban 설정
├── docs/               # 사용·인증·연동·API·운영 문서
├── scripts/            # 공개 전 파일 검사 등 관리 도구
├── docker-compose.yml
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
| GitHub 공개·제외 규칙·소스 압축본 | [공개 준비](docs/publishing.md) |
| HTTP 요청·응답 계약 | [API](docs/api.md) |

공개 전 프로젝트 루트에서 `python3 scripts/check_publish.py`를 실행하세요. `.env`, 운영 DB, `.local-backups/`, `logs/`, 의존성·빌드 결과는 저장소와 Docker 빌드 컨텍스트에서 제외합니다. 포함된 원본 라이선스는 [frontend/CATPPUCCIN-STARTPAGE-LICENSE](frontend/CATPPUCCIN-STARTPAGE-LICENSE)에 있습니다.

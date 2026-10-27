# GitHub 공개 준비

[프로젝트 소개·실행](../README.md)

GitHub에 올릴 프로젝트 루트는 `CatppuccinDock/`입니다. 상위 작업 폴더나 서버 전체를 업로드하지 않습니다.

## 포함할 파일

| 위치 | 내용 |
| --- | --- |
| `frontend/src/`, `frontend/public/`, `frontend/tests/` | Vue 소스·정적 리소스·테스트 |
| `backend/app/`, `backend/tests/` | FastAPI 소스·기본 데이터·테스트 |
| `deploy/` | Garage 설정·nginx/Fail2ban 예시 |
| `.github/` | 테스트·GHCR 이미지 게시 워크플로·Action 업데이트 설정 |
| `docs/` | 사용·개발·API·운영 문서 |
| `scripts/` | 스토리지 초기 설정·공개 전 검사 |
| 루트·각 앱의 빌드 설정 | Compose·Dockerfile·의존성 목록·lockfile·ignore 규칙 |
| `.env.example`·라이선스 | 빈 비밀값을 가진 설정 예시·포함된 원본 라이선스 |

기본 북마크 JSON과 로컬 아이콘 목록은 새 계정용 소스 데이터입니다. 실제 사용자의 북마크·계정은 운영 PostgreSQL에 저장됩니다. 기본 데이터·폰트·아이콘·PWA 리소스와 라이선스는 소스에 포함합니다.

저장소의 `main` 대상 PR에서 검증하고, 버전 태그를 푸시했을 때만 출시 검사를 거쳐 GHCR 이미지와 GitHub 릴리즈를 게시합니다. `main` 머지만으로는 이미지를 게시하지 않습니다. 필수 체크·권한·패키지 공개 설정은 [GitHub Actions 설정](github-actions.md)에, 이미지 사용 방법은 [컨테이너 빌드·배포](containers.md)에 있습니다.

## 서버에만 보관할 파일

`.gitignore`와 세 Docker 컨텍스트의 `.dockerignore`에서 다음 항목을 제외합니다.

- 실제 `.env`·환경 설정·키·인증 파일
- DB 덤프·로그와 회전 로그·사용자 JSON/HTML 내보내기
- `.local-backups/`, `logs/`, `uploads/`, `exports/`, `storage/`
- `postgres_data/`, `garage_meta/`, `garage_data/` 등 볼륨 복사본
- `node_modules/`, `.venv/`, 빌드·테스트 결과·캐시·임시 파일
- 로컬 IDE·에이전트 설정과 실제 프록시/Fail2ban 설정

운영 중인 `.env`, DB, Garage 파일, 로그와 백업은 삭제하지 않습니다. Compose의 DB·Garage 데이터는 Docker named volume에 보존되며 Git 작업 디렉터리와 별개입니다. GIF·업로드 아이콘은 비공개 Garage에, 파일 정보·SSO/API 비밀값은 DB에 저장합니다.

사용자 백업 파일은 `exports/`나 `.local-backups/`에 보관하세요. 앱이 내려주는 `catppuccindock*.json`과 `bookmarks.html`도 기본 제외하지만, 이름을 바꾼 임의 JSON까지 자동으로 구별할 수는 없습니다.

## 검사와 소스 압축본

프로젝트 루트에서 실행합니다.

```bash
python3 scripts/check_publish.py
```

실제 Git ignore 규칙으로 후보 파일을 선정하고, 실제 `.env` 비밀값의 복사본·대표적인 토큰·개인키·덤프 패턴을 검사합니다. 값은 출력하지 않습니다. 이미 추적 중인 제외 파일은 실패로 표시합니다. Git 초기화 전에도 임시 Git 메타데이터로 검사하며 프로젝트의 Git 인덱스를 변경하지 않습니다.

검사에 통과한 소스만 압축하려면 다음을 실행합니다.

```bash
python3 scripts/check_publish.py --archive .local-backups/CatppuccinDock-source.tar.gz
```

압축본에는 검사한 파일 내용만 포함하며 `.env`, 실행 데이터, 의존성은 넣지 않습니다. 기존 압축본은 덮어쓰지 않으므로 재생성할 때 새 파일 이름을 사용하세요. 압축을 푼 새 환경에서는 `sh scripts/init-env.sh`로 시크릿을 준비하고 기본 Compose로 이미지를 실행하거나 `compose.build.yml`을 함께 지정해 소스에서 빌드할 수 있습니다.

이 검사는 현재 파일을 대상으로 하며 Git 커밋 이력이나 외부 서비스의 데이터를 검사하지 않습니다. 실제 비밀값이 과거 커밋에 들어간 저장소라면 이력 정리와 해당 키 교체가 별도로 필요합니다. GitHub 저장소 생성·커밋·푸시는 자동으로 수행하지 않습니다.

공개 검사 도구의 차단·압축·덮어쓰기 방지 검증은 `python3 -m unittest discover -s scripts/tests -v`로 실행합니다. 임시 저장소만 사용하며 운영 파일과 Git 인덱스를 수정하지 않습니다.

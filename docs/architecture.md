# 프로젝트 구조

[프로젝트 소개·실행](../README.md)

## 프론트엔드 구조

```text
frontend/src/
├── App.vue             # 세션 상태와 화면 진입
├── main.js             # 앱 시작·전역 스타일
├── views/              # 메인·로그인·관리자 화면
├── components/
│   ├── common/         # 드롭다운·아이콘·로그아웃
│   ├── bookmarks/      # 북마크 편집·아이콘·즐겨찾기
│   ├── backgrounds/    # GIF 라이브러리·검색·업로드
│   ├── search/         # 통합 검색
│   ├── statusbar/      # 하단바·시계·날씨·모니터링
│   └── settings/       # 계정·공개 링크·관리자 설정
├── composables/        # Vue 공통 상태·테마
├── directives/         # 드래그 정렬 지시자
├── lib/                # API·주소·검색·배경·아이콘 처리
├── styles/             # 전역 테마와 화면별 스타일
└── assets/             # WOFF2 폰트·SVG 아이콘·파비콘
```

공통 테마와 컨트롤 스타일은 `main.js`에서 한 번 불러오고, 화면별 스타일은 해당 화면에서 불러옵니다. 새 사용자 기본 데이터의 원본은 `backend/app/data/startpage.json`이며 프론트에는 복사본을 두지 않습니다. 프론트 테스트는 `frontend/`에서 `npm test`, 프로덕션 빌드는 `npm run build`로 실행합니다.

## 백엔드 구조

```text
backend/
├── app/
│   ├── main.py       # FastAPI 앱 구성·시작·상태 확인
│   ├── cli.py        # 운영자용 계정 복구 명령
│   ├── api/          # HTTP 엔드포인트와 인증·권한 의존성
│   ├── schemas/      # 요청 데이터 검증
│   ├── services/     # 인증·북마크·프록시·모니터링 로직
│   │   └── media/    # GIF 저장·검색·제공처·최적화·사용 한도
│   ├── db/           # DB 연결·모델·데이터 이전
│   ├── core/         # 암호화·비밀번호·인증 코드 처리
│   └── data/         # 새 사용자에게 제공할 기본 데이터
├── tests/
├── Dockerfile
└── requirements.txt
```

`backend/`를 작업 디렉터리로 사용합니다. 내부 모듈은 `app.*` 절대 경로로 가져오며, API 모듈 간에 공통 기능을 가져오는 대신 `services/`를 통해 공유합니다.


## 파일 배치 기준

기본 `docker-compose.yml`은 GHCR 이미지를 실행하며 Garage 설정을 내장합니다. 로컬 소스 빌드는 `compose.build.yml`로 분리하고, 시크릿 초기화는 `scripts/init-env.sh`에서 처리합니다. 이미지 설치는 문서의 OpenSSL 명령 또는 외부 시크릿 주입을 사용하므로 초기화 스크립트를 다운로드할 필요가 없습니다.

UI는 `frontend/src/components/`의 기능별 폴더에, API 주소·시계 등 여러 화면이 공유하는 로직은 `frontend/src/lib/`에 둡니다. GIF 관련 백엔드 로직은 `backend/app/services/media/`에 모으고 HTTP 경로는 `backend/app/api/`에서 처리합니다. API 계약은 [docs/api.md](api.md)에 있습니다.

소스에서 쓰지 않는 기본 배너·아이콘 웹폰트·중복 TTF는 제거했습니다. 메뉴 배경 파일은 비공개 Garage/S3에, 소유권·출처·저장 경로는 DB에 보관합니다. 이전 DB 파일도 이관 전까지 읽을 수 있습니다. 아이콘은 SVG를, 글꼴은 WOFF2를 사용합니다. 이전 백업을 읽기 위한 배너 식별자 검증은 유지합니다. [스토리지 운영 안내](storage.md)

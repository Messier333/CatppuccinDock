# Garage · S3 파일 저장

GIF 파일 본문은 S3 호환 스토리지에 저장하고 PostgreSQL에는 이름·소유자·출처·용량·크기·SHA-256·버킷·객체 키를 보관합니다. 기본 Compose는 Garage v2.4.1을 같은 서버에서 실행합니다. 원래 GIF 주소(`/api/backgrounds/{id}/content`)를 유지하며 로그인·소유권 검사 후 백엔드가 파일을 제공합니다. 브라우저에 S3 키나 공개 버킷 URL을 전달하지 않습니다. 목록과 ETag 304 응답은 S3에서 파일을 읽지 않습니다.

업로드한 북마크 아이콘도 같은 저장소의 `{S3_KEY_PREFIX}/icons/{사용자ID}/{UUID}.png`에 보관합니다. DB의 `dock_uploaded_icons`에는 파일 메타데이터만 저장합니다. 아이콘 내용은 소유권 또는 공개 링크 권한 검사 후 `/api/uploaded-icons/{id}/content`에서 제공합니다. JSON·암호화 백업에는 선택에 따라 GIF와 아이콘 본문이 함께 포함됩니다. [아이콘 업로드 안내](usage.md#아이콘-검색선택업로드)

## 초기 설정

```bash
cp .env.example .env
# DB·로그인·암호화 키 입력 후 실행
python3 scripts/setup_storage.py
docker compose up --build -d --wait
```

설정 도구는 기존 키를 바꾸거나 출력하지 않습니다. Garage는 내부 `http://garage:3900`에서만 접근할 수 있으며 RPC·S3·관리 포트를 호스트에 노출하지 않습니다. 전용 `catppuccindock` 버킷과 키는 최초 기동 시 생성합니다. 파일 경로는 `catppuccindock/backgrounds/{사용자ID}/{임의UUID}.gif`입니다. 같은 사용자의 동일 파일은 기존 DB 메타데이터로 중복을 방지하고 다른 계정의 검증된 캐시는 해당 사용자 객체로 복사합니다.

| 환경변수 | 기본값 / 용도 |
| --- | --- |
| `MEDIA_STORAGE_BACKEND` | Compose 기본 `s3`; 로컬 개발·기존 설치 호환용 `database` 지원 |
| `S3_ENDPOINT_URL` | `http://garage:3900`; 외부 S3는 HTTPS 사용 |
| `S3_REGION` | `garage`; Garage 구성의 리전과 일치해야 함 |
| `S3_BUCKET` | `catppuccindock` |
| `S3_KEY_PREFIX` | `catppuccindock`; 다른 앱과 구분되는 전용 경로 |
| `S3_ACCESS_KEY_ID` · `S3_SECRET_ACCESS_KEY` | 전용 버킷 접근 키; 서버 `.env`에만 보관 |
| `GARAGE_RPC_SECRET` | Garage 노드 통신 키; 최초 생성 후 유지 |

외부 Garage/S3를 사용하려면 S3 환경변수를 해당 저장소로 지정하고 Compose의 로컬 `garage` 의존성과 서비스를 조정하세요. 파일이 있는 버킷·리전·엔드포인트·키를 무작정 교체하면 기존 파일을 읽을 수 없습니다. Garage 생성용 키의 `.env` 값만 바꿔도 기존 키가 교체되는 것은 아닙니다. 키 교체는 Garage에서 새 키 생성·권한 부여 후 백엔드 설정을 바꾸는 절차로 진행하세요.

## 기존 DB GIF 이관

먼저 기존 DB와 `.env`를 별도로 백업합니다. 새 백엔드를 기동하면 저장 경로 열을 추가하고 파일 본문 열을 NULL 허용으로 변경합니다. 이전 DB GIF도 계속 읽을 수 있습니다. 신규 파일은 S3 장애 시 DB로 우회 저장하지 않고 503 오류를 반환합니다.

```bash
# 대상 개수만 확인
docker compose exec -T backend python -m app.services.media.migrate_storage
# 한 파일씩 복사 → 다시 읽어 길이·SHA-256 검증 → DB 본문 제거 → 커밋
docker compose exec -T backend python -m app.services.media.migrate_storage --apply
```

파일 ID·탭 연결·소유권·출처는 바꾸지 않습니다. 검증 실패 시 해당 파일의 DB 원본과 저장 경로 변경을 롤백하고 복사본 삭제를 예약합니다. 중단되면 명령을 다시 실행하면 됩니다. 이관 후 기존 DB 바이트는 NULL이며 PostgreSQL의 일반 VACUUM으로 해당 공간을 재사용할 수 있습니다. `VACUUM FULL`은 테이블을 잠그므로 자동 실행하지 않습니다.

## 삭제·장애 처리

사용 중인 GIF와 휴지통에서 참조하는 GIF는 기존처럼 삭제할 수 없습니다. 삭제 가능한 파일은 메타데이터 삭제와 S3 삭제 예약을 같은 DB 트랜잭션으로 기록하고, 백그라운드 작업이 30초 간격으로 최대 20개씩 제거합니다. 저장소 장애가 나도 예약은 DB에 남아 재시작 후 재시도하며 참조 중인 객체는 지우지 않습니다. 일반 롤백으로 남은 신규 업로드도 삭제 예약으로 정리합니다. S3 업로드와 DB 커밋 사이의 강제 종료 등에서는 참조 없는 객체가 남을 수 있으므로 운영 점검 시 전용 경로의 객체와 DB 메타데이터를 대조하세요. 이를 자동으로 무차별 삭제하지 않습니다.

콘텐츠 조회와 이관은 DB의 파일 길이·SHA-256으로 S3 내용을 검증합니다. `/api/health`는 DB와 구성된 저장 버킷 접근을 검사하며 응답에 저장 방식을 포함합니다. 인증 정보·서명·엔드포인트는 사용자 오류 메시지에 포함하지 않습니다.

## 백업·복원

앱의 JSON·암호화 내보내기는 S3에서 파일 본문을 읽어 기존 백업 형식에 포함합니다. 다른 서버·계정으로 가져오면 그 서버의 저장소에 새 객체를 만들므로 S3 경로에 종속되지 않습니다. S3 장애 중에는 파일을 포함한 백업도 오류를 반환하며 불완전한 백업을 만들지 않습니다. 이미지가 포함된 가져오기 미리 보기는 기존처럼 암호화된 임시 DB 기록에 최대 10분간 보관합니다.

**서버 전체 백업은 PostgreSQL 덤프만으로 충분하지 않습니다.** `.env`, PostgreSQL, `garage_meta`, `garage_data`를 함께 보관하세요. 스토리지 볼륨의 일관된 백업은 앱 쓰기를 멈추고 Garage를 정지한 상태에서 두 볼륨을 함께 복사하거나 별도 S3 백업 대상으로 객체와 DB를 함께 백업하는 방식으로 수행합니다. `docker compose down -v`는 모든 데이터 볼륨을 삭제하므로 사용하지 마세요.

현재 구성은 한 서버·복제 수 1이며 다른 서버로 복제하지 않습니다. 디스크 장애 대비에는 별도 백업이 필요합니다. 다중 노드가 필요하면 [Garage 클러스터 운영 안내](https://garagehq.deuxfleurs.fr/documentation/cookbook/real-world/)에 따라 구성하세요. [Garage 공식 초기 설정](https://garagehq.deuxfleurs.fr/documentation/quick-start/)

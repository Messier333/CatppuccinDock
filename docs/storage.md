# Garage · S3 파일 저장

GIF 파일 본문은 S3 호환 스토리지에 저장하고 PostgreSQL에는 이름·소유자·출처·용량·크기·SHA-256·버킷·객체 키를 보관합니다. 기본 Compose는 Garage v2.4.1을 같은 서버에서 실행합니다. 원래 GIF 주소(`/api/backgrounds/{id}/content`)를 유지하며 로그인·소유권 검사 후 백엔드가 파일을 제공합니다. 브라우저에 S3 키나 공개 버킷 URL을 전달하지 않습니다. 목록과 ETag 304 응답은 S3에서 파일을 읽지 않습니다.

업로드한 북마크 아이콘도 같은 저장소의 `{S3_KEY_PREFIX}/icons/{사용자ID}/{UUID}.png`에 보관합니다. DB의 `dock_uploaded_icons`에는 파일 메타데이터만 저장합니다. 아이콘 내용은 소유권 또는 공개 링크 권한 검사 후 `/api/uploaded-icons/{id}/content`에서 제공합니다. JSON·암호화 백업에는 선택에 따라 GIF와 아이콘 본문이 함께 포함됩니다. [아이콘 업로드 안내](usage.md#아이콘-검색선택업로드)

## 초기 설정

[빠른 설치](../README.md#빠른-설치)의 명령으로 파일과 시크릿을 준비하거나 [외부 시크릿 저장소](secrets.md)에서 환경변수를 주입합니다. `.env` 배포는 다음과 같이 실행합니다.

```bash
docker compose up -d --wait
```

Garage는 내부 `http://garage:3900`에서만 접근할 수 있으며 RPC·S3·관리 포트를 호스트에 노출하지 않습니다. 전용 `catppuccindock` 버킷과 키는 최초 기동 시 생성합니다. 파일 경로는 `catppuccindock/backgrounds/{사용자ID}/{임의UUID}.gif`입니다. 같은 사용자의 동일 파일은 기존 DB 메타데이터로 중복을 방지하고 다른 계정의 검증된 캐시는 해당 사용자 객체로 복사합니다.

| 환경변수 | 기본값 / 용도 |
| --- | --- |
| `MEDIA_STORAGE_BACKEND` | Compose 기본 `s3`; 로컬 개발·기존 설치 호환용 `database` 지원 |
| `S3_ENDPOINT_URL` | `http://garage:3900`; 외부 S3는 HTTPS 사용 |
| `S3_REGION` | `garage`; Garage 구성의 리전과 일치해야 함 |
| `S3_BUCKET` | `catppuccindock` |
| `S3_KEY_PREFIX` | `catppuccindock`; 다른 앱과 구분되는 전용 경로 |
| `S3_ACCESS_KEY_ID` · `S3_SECRET_ACCESS_KEY` | 전용 버킷 접근 키; 서버 `.env` 또는 시크릿 저장소에 보관 |
| `GARAGE_RPC_SECRET` | Garage 노드 통신 키; 최초 생성 후 유지 |

외부 Garage/S3를 사용하려면 S3 환경변수를 해당 저장소로 지정하고 Compose의 로컬 `garage` 의존성과 서비스를 조정하세요. 파일이 있는 버킷·리전·엔드포인트·키를 무작정 교체하면 기존 파일을 읽을 수 없습니다. Garage 생성용 키의 `.env` 값만 바꿔도 기존 키가 교체되는 것은 아닙니다. 키 교체는 Garage에서 새 키 생성·권한 부여 후 백엔드 설정을 바꾸는 절차로 진행하세요.

기본 Compose에 Garage 설정이 포함되어 있어 별도 TOML 파일을 내려받지 않아도 됩니다.

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


## DB·Garage 업데이트

앱의 `IMAGE_TAG=latest`는 프론트·백엔드에만 적용됩니다. 현재 기본 Compose는 DB를 `postgres:17-alpine`, Garage를 `dxflrs/garage:v2.4.1`로 지정합니다. 앱 이미지 업데이트와 DB·스토리지 엔진 업데이트를 구분합니다.

| 대상 | 방법 |
| --- | --- |
| 앱의 테이블·열 변경 | 현재 구현된 스키마 변경은 새 백엔드 시작 시 적용됩니다. PostgreSQL 엔진 버전은 바꾸지 않습니다. |
| PostgreSQL 17 계열의 패치 | 같은 메이저 안에서 이미지 갱신·컨테이너 재생성. 릴리즈 노트의 추가 작업도 확인합니다. |
| PostgreSQL 17 → 18 등 메이저 변경 | 새 데이터 볼륨에 덤프·복원하거나 검증된 `pg_upgrade` 절차로 이전합니다. |
| Garage의 호환되는 업데이트 | 대상 버전·설정을 확인하고 해당 이미지로 재생성합니다. |
| Garage의 데이터 형식 변경 | 해당 버전의 공식 마이그레이션 절차를 따릅니다. |
| 외부 S3·관리형 DB | 해당 서비스에서 엔진을 관리합니다. 앱의 접속 설정은 서비스 안내에 따라 변경합니다. |

### 공통 준비와 복구

1. 현재 Compose 파일·실행 이미지 버전 또는 digest·시크릿을 보관합니다.
2. 앱 쓰기를 멈춘 상태에서 PostgreSQL 덤프와 Garage의 `garage_meta`·`garage_data`를 함께 백업합니다. Garage 볼륨은 Garage를 정지하거나 공식 스냅샷 절차를 사용해 복사합니다. 백업을 위해 정지했다면 기존 버전의 DB·Garage를 다시 기동해 정상 상태를 확인합니다. [백업·복원](#백업복원)
3. 별도 환경에서 복원이 되는지 확인하고, 대상 버전의 호환성·설정 변경·추가 마이그레이션을 확인합니다.
4. 현재 구성은 단일 서버이므로 DB·Garage 재시작 중 점검 시간이 발생합니다. 한 서비스씩 업데이트하고 로그인·북마크·기존 GIF/아이콘 조회·새 업로드를 확인합니다.

실패하면 앱을 멈춘 상태로 유지하고 원인을 확인합니다. 데이터 형식이 바뀐 뒤에는 이전 이미지 태그로만 되돌리지 않고, 호환되는 이미지·설정과 업데이트 전 백업을 함께 복원합니다. 동일한 Compose 프로젝트 이름과 볼륨을 유지하고 `docker compose down -v`는 실행하지 않습니다.

### PostgreSQL 17 계열의 패치 업데이트

현재처럼 `postgres:17-alpine`을 사용하면 같은 17 계열의 새 이미지가 게시됐을 때 아래처럼 갱신합니다. **위 백업·복구 준비를 마친 뒤** 기존 설치 디렉터리에서 실행합니다. 각 단계가 성공했는지 확인하고 다음 명령으로 진행하세요.

```bash
docker compose pull database
docker compose stop frontend backend
docker compose up -d --wait --no-deps database
docker compose up -d --wait --no-deps backend
docker compose up -d --wait --no-deps frontend
docker compose ps
```

`--no-deps`는 점검 중 다른 서비스를 함께 재생성하지 않도록 합니다. DB 준비나 백엔드 상태 검사에 실패하면 앱을 다시 열기 전에 복구합니다. PostgreSQL은 같은 메이저의 마이너 버전끼리 데이터 형식이 호환되지만, 릴리즈 노트에 명시된 후속 작업은 수행해야 합니다. [PostgreSQL 업그레이드 안내](https://www.postgresql.org/docs/current/upgrading.html)

### PostgreSQL 메이저 업그레이드

`postgres:17-alpine`을 `postgres:18-alpine`로 바꾸고 기존 데이터 볼륨을 그대로 연결하는 방식으로 진행하지 않습니다.

1. 새 버전에 맞는 별도 DB 서비스·새 데이터 볼륨을 준비합니다.
2. 앱을 멈추고 최종 덤프를 만든 뒤 새 DB에 복원하거나, 별도로 검증한 `pg_upgrade` 절차를 실행합니다.
3. 앱과 데이터·권한을 검증한 뒤 새 DB로 전환합니다.
4. 복구 가능 기간 동안 기존 DB 볼륨·덤프·이전 Compose 구성을 보관합니다.

새 PostgreSQL Docker 이미지의 `PGDATA`와 볼륨 마운트 경로도 확인해야 합니다. 18 이상은 기본 디렉터리 구조가 17 이하와 다르므로 이 프로젝트의 기존 볼륨 경로만 재사용하지 않습니다. 메이저 업그레이드는 앱이 자동 수행하지 않습니다. [PostgreSQL 공식 이미지 안내](https://github.com/docker-library/docs/blob/master/postgres/README.md) · [pg_upgrade](https://www.postgresql.org/docs/current/pgupgrade.html)

### Garage 업데이트

현재는 정확한 버전 `v2.4.1`에 고정돼 있으므로 `docker compose pull garage`만으로 다른 버전으로 바뀌지 않습니다. 먼저 대상 버전의 변경 내역과 업그레이드 안내를 확인하고 백업합니다. 호환되는 업데이트라면 Compose의 `garage.image`를 **검증한 대상 태그**로 변경한 뒤 진행합니다.

```bash
docker compose pull garage
docker compose stop frontend backend
docker compose up -d --wait --no-deps garage
docker compose up -d --wait --no-deps backend
docker compose up -d --wait --no-deps frontend
docker compose ps
```

이 명령은 별도 데이터 마이그레이션이 필요 없는 호환 업데이트용입니다. 메이저 변경에는 버전별 전용 절차가 있을 수 있으며, 버전을 건너뛰는 업그레이드도 지원 여부를 확인합니다. 기존 S3 키·버킷·RPC 시크릿·두 Garage 볼륨은 유지합니다. [Garage 공식 업그레이드 안내](https://garagehq.deuxfleurs.fr/documentation/operations/upgrading/)

Infisical을 사용한다면 위의 각 Compose 명령에도 동일한 시크릿 주입을 적용합니다. [시크릿 저장소 실행 방법](secrets.md#업데이트와-키-변경)

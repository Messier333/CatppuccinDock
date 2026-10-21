# API

인증: `catppuccindock_session` HttpOnly 쿠키. 변경 요청에는 `X-CatppuccinDock: 1` 헤더와 JSON을 사용합니다. GIF 업로드는 JSON 대신 GIF 원본 바이트를 전송합니다. CORS는 허용하지 않습니다. 일반 API 응답은 `Cache-Control: no-store`이며 이미지 응답의 캐시 정책은 아래에 명시합니다.

| 경로 | 메서드 | 권한·동작 |
|---|---|---|
| `/api/auth/status` | GET | 로그인·최초 설정·2FA 대기·SSO 활성 상태, `password_login_enabled` |
| `/api/auth/setup` | POST | 최초 관리자 생성: `username,password,setup_code` |
| `/api/auth/login` | POST | `username,password`; `mfa_required=true`면 추가 인증 필요 |
| `/api/auth/mfa` | POST | `code`: 인증 앱 코드 또는 일회용 복구 코드 |
| `/api/auth/logout` | POST | 현재 세션 및 대기 중인 2FA 요청 폐기 |
| `/api/auth/oidc/login` | GET | OIDC 인증 서비스로 이동 |
| `/api/auth/oidc/callback` | GET | 설정한 고정 callback; 사용자 지정 이동 주소는 받지 않음 |
| `/api/account` | GET | 본인 계정·2FA·복구 코드 잔여 수 |
| `/api/account/password` | POST | `current_password,new_password`; 다른 세션 폐기 |
| `/api/account/sessions` | GET | 본인 유효 로그인 목록. `offset` 기본 0, `limit` 기본 5·최대 50. `current_session`, 다른 기기 `items`, `total_others,offset,limit` 반환 |
| `/api/account/sessions/{id}` | DELETE | 본인 기기만 로그아웃; 공개 UUID 사용. 없는/다른 사용자/만료 기기는 404. 현재 기기면 쿠키 삭제 후 `current_revoked:true` |
| `/api/account/sessions/revoke-others` | POST | 현재 세션을 보존하고 본인 다른 세션과 진행 중인 2FA 로그인을 폐기. `{ok,revoked}` 반환 |
| `/api/account/2fa/enroll` | POST | `password`; SSO 전용 사용자는 최근 로그인 확인. QR·설정 키 반환 |
| `/api/account/2fa/confirm` | POST | `code`; 등록 완료와 복구 코드 10개 반환 |
| `/api/account/2fa/disable` | POST | `password,code`; 설정·복구 코드 제거 |
| `/api/account/2fa/recovery-codes` | POST | `password,code`; 이전 코드를 폐기하고 새 코드 반환 |
| `/api/portal` | GET | 로그인한 사용자의 DB 기반 탭·카테고리·북마크와 공통 설정 |
| `/api/tabs` | POST | `name,banner,background_id?,position`; background_id는 본인 GIF의 UUID 또는 null |
| `/api/tabs/{id}` | PUT, DELETE | 본인 소유만; 마지막 탭 삭제 불가 |
| `/api/categories` | POST | `tab_id,name,position` |
| `/api/categories/{id}` | PUT, DELETE | 본인 소유 탭·카테고리만 |
| `/api/bookmarks` | POST | `category_id,name,url,icon,icon_color,position` |
| `/api/bookmarks/{id}` | GET, PUT, DELETE | 본인 소유만. PUT은 전체 필드 전달 |
| `/api/admin/me` | GET | 관리자만 |
| `/api/admin/users` | GET, POST | 관리자만; 생성: `username,role,active,login_type`; local은 `password`, oidc는 `oidc_subject` 필수 |
| `/api/admin/users/{id}` | PUT | `username,role,active,password?`; 마지막 관리자 보호 |
| `/api/admin/users/{id}/identities` | POST | `issuer,subject`; 관리자에 의한 명시적 SSO 연결 |
| `/api/admin/users/{id}/identities/{identity_id}` | DELETE | 관리자만; 유일한 로그인 수단 제거 불가 |
| `/api/admin/settings` | GET, PUT | 관리자만; `search_engine(d/g/p/y),search_open_mode(same_tab/new_tab),timezone,clock_format(12h/24h),weather_location,temperature_scale,bookmark_shelf_display(labels/icons)` |
| `/api/admin/sso` | GET, PUT | 관리자만; `enabled,login_mode(both/sso_only),label,issuer,client_id,redirect_uri,client_secret?`; null secret은 기존 값 유지, 응답에 secret 없음 |
| `/api/admin/proxy-sources` | GET, POST | 관리자만; `name,provider(npm/npg/zoraxy/custom),base_url,token,verify_tls,custom_api?` |
| `/api/admin/proxy-sources/{id}` | PUT, DELETE | 관리자만; 수정 시 null token 유지, 주소·종류 변경 시 새 token 필수 |
| `/api/admin/proxy-sources/{id}/preview` | POST | 관리자만; `scheme(auto/http/https),public_port?`; 10분 유효 `preview_id,entries,skipped` 반환 |
| `/api/admin/proxy-sources/{id}/import` | POST | 관리자만; `preview_id,category_id,entry_ids`; 본인 카테고리, 서버 미리 보기 내 링크만 저장; `added,duplicates` 반환 |
| `/api/health` | GET | DB·구성된 파일 저장소 상태 검사, 인증 불필요. 정상 시 `status:ok,database:ok,storage:s3`(또는 database); 저장소 장애는 503 |

`role`: `admin` 또는 `member`. `banner`: `banner_11`, `banner_07`, `banner_15`. `icon_color`: 기본값 `auto`(카테고리 내 순서와 테마에 따른 자동 색상) 또는 `#`와 6자리 16진수(직접 지정). 새 북마크·공개 링크·API 가져오기는 기본 자동 색상이며, `auto`로 수정하면 직접 지정 색상을 해제합니다. URL은 HTTP/HTTPS만 허용합니다. `position`은 0~10000이고 작은 수가 먼저 표시됩니다. 수정 가능한 데이터 모델은 `user_id`, `role` 등의 임의 필드를 거부합니다.

대표 오류: `401` 로그인 또는 추가 인증 필요, `403` 권한·재인증 실패, `404` 본인 소유 항목 없음, `409` 중복·마지막 관리자/탭 보호, `422` 입력 검증 실패, `429` 반복 시도 제한.

## 업로드 GIF 배경

| 경로 | 메서드 | 설명 |
| --- | --- | --- |
| `/api/backgrounds` | GET | `usage`에 허용 여부·일일 횟수/바이트·저장 용량·기준 시간대를 제공. 본인 GIF 메타데이터 `items`와 제한 `limits`; 이름·크기·해상도·프레임 수·사용 중인 탭 수 포함, 이미지 바이트 제외 |
| `/api/backgrounds` | POST | 로그인 사용자 + 변경 헤더; `Content-Type: image/gif`(또는 application/octet-stream), GIF 원본 본문; 선택 헤더 `X-File-Name`은 URL 인코딩한 이름. 원본 100MB·저장 파일 10MB·20개 제한, 큰 GIF 자동 최적화, 같은 사용자 내 동일 저장 파일 재사용 |
| `/api/backgrounds/{id}/content` | GET | 로그인 및 소유권 확인 후 image/gif; `Cache-Control: private, no-cache`, `Vary: Cookie`, ETag 조건부 요청은 304 |
| `/api/backgrounds/{id}` | DELETE | 본인 미사용 GIF 삭제; 사용 중이면 409. 탭을 삭제해도 라이브러리 파일은 보존 |

신규 GIF 본문은 기본 Compose의 비공개 Garage/S3에 저장하며 기존 DB 파일은 이관 전까지 읽을 수 있습니다. 목록·304에는 S3 본문 조회가 없으며 파일 내용은 DB의 길이·SHA-256으로 검증합니다. 저장소 장애는 503이며 DB로 우회 저장하거나 공개 URL로 리다이렉트하지 않습니다. 삭제는 메타데이터 제거와 영속 삭제 예약 후 백그라운드에서 재시도합니다. JSON·암호화 백업 형식은 파일 본문을 포함하여 유지합니다. [스토리지 구성·이관](storage.md)

`/api/portal`의 탭에 `background_id`가 있으면 해당 이미지 경로를 사용하고 null이면 기존 `banner`를 사용합니다. 탭 생성·수정 시 타인의 이미지나 삭제된 이미지는 404입니다. GIF 업로드의 잘못된 MIME은 415, 크기 초과는 413, 손상된 파일·디코딩 제한 초과는 422입니다. 전체 프레임을 검증합니다. 저장 한도에 맞으면 원본 바이트를 보관하고, 초과하면 해상도·프레임·색상 수를 줄여 애니메이션 GIF로 저장합니다. `limits.max_bytes`는 저장 한도 10MiB, `limits.max_input_bytes`는 원본 한도 100MiB입니다. 최적화 작업은 단일 별도 프로세스에서 메모리 512MiB·최대 60초로 제한하며, 사용 중이면 503을 반환합니다. 검색/업로드/가져오기의 바깥 프록시 제한도 100MiB·180초입니다. `/api/backgrounds/search`에서 제공처가 없는 주제에 404를 반환하면 200의 빈 목록을 반환하며 실제 장애·요청 제한은 오류로 유지합니다.

### GIF 검색·악용 방지 정책

- `GET /api/backgrounds/providers`: 로그인 사용자에게 선택 가능한 제공처만 반환합니다. API 키는 포함하지 않습니다.
- `GET /api/backgrounds/search?provider=all&q=pixel%20art&page=1`: 통합 검색. `gifdb,pixabay,alphacoders,motionbgs,commons,openverse` 개별 선택도 가능하며, 통합 검색의 `unavailable`은 실패한 일부 제공처 이름입니다. 각 결과의 `source.provider`로 가져오세요.
- `POST /api/backgrounds/import`: `{provider,item_id}`. 검증된 캐시를 우선 사용하며 새 다운로드는 DB의 횟수·용량 예약 이후 수행합니다. Pixabay MP4는 최대 처음 20초를 GIF로 변환합니다.
- `GET/PUT /api/admin/backgrounds`: 관리자만 GIF 정책과 Pixabay 키를 관리합니다. `member_import,member_upload,member_per_minute,member_per_day,member_daily_mb,member_storage_mb,server_per_day,server_daily_mb,server_storage_mb`와 선택 `pixabay_key,clear_pixabay_key`. 응답에는 `has_pixabay_key`만 포함합니다. PUT은 변경 헤더가 필요합니다.
- 기본 일반 사용자 한도는 분당 1회·하루 5회·원본 200MiB·저장 200MiB/20개이며, 전체 한도는 하루 100회·원본 2GiB·저장 2GiB입니다. 관리자는 개인 횟수/용량 제한에서 제외되지만 전체 한도를 적용합니다.
- 일일 사용량은 공통 시계 시간대의 자정에 초기화됩니다. 실패·삭제·로그아웃·재시작으로 초기화되지 않습니다. 전송 중에는 최대 수신량을 예약하고 종료 시 실제 수신 바이트로 정산하며, 비정상 종료 예약은 당일 한도에 남습니다. 동시 처리 잠금은 5분 후 만료됩니다.
- 403은 관리자가 일반 사용자 기능을 끈 경우, 409는 저장 공간 부족, 429는 횟수/용량 한도, 503은 다른 작업 진행 중입니다. 탭/카테고리 생성과 이미 저장된 GIF 선택은 계속 가능합니다.
- 공유 캐시는 서버가 실제로 검증한 제공처 키만 사용합니다. 백업의 출처 메타데이터만으로 다른 사용자의 데이터를 재사용하지 않습니다.

## 공개 링크·아이콘

| 경로 | 메서드 | 설명 |
| --- | --- | --- |
| `/api/admin/proxy-sources/providers` | GET | 관리자만; 앱 선택 목록 (NPM/NPG/Zoraxy) |
| `/api/admin/proxy-sources/{id}/import` | POST | `destination=library`와 선택 entry_ids로 공개; 기본 private는 본인 카테고리에 저장 |
| `/api/admin/library` | GET | 관리자만; 공개·비공개 목록 |
| `/api/admin/library/{id}` | PUT | 관리자만; `name,icon,icon_color,published`; 숨김은 개인 구독에도 적용 |
| `/api/library` | GET | 로그인 사용자; 공개된 링크만, 본인 추가 여부 `added` 포함; 연결 주소·토큰은 반환하지 않음 |
| `/api/library/add` | POST | `category_id,link_ids`; 선택한 공개 링크를 원자적으로 본인 카테고리에 추가, 중복은 건너뛰고 `added,duplicates` 반환; 비공개·삭제된 항목 포함 시 409 |
| `/api/library/{id}/add` | POST | `category_id`; 공개 링크를 본인 카테고리에 추가, 중복 409 |
| `/api/icons/collections` | GET | 로그인 사용자; 컬렉션·개수·라이선스 |
| `/api/icons?collection=tabler&q=server&offset=0` | GET | 로그인 사용자; 48개 검색 결과, `total,has_more` |
| `/api/icons/{prefix:name}.svg` | GET | 로그인 사용자; 서버 제공 SVG, private 캐시 24시간 |
| `/api/uploaded-icons?q=` | GET | 본인 업로드 아이콘 목록과 제한. `items`의 `id,icon,name,byte_size,used_by,in_trash`; 파일 바이트·저장 경로 제외 |
| `/api/uploaded-icons` | POST | 로그인 + 변경 헤더. 원본 이미지 바이트, 선택 `X-File-Name` URL 인코딩. 5MiB까지 PNG/JPEG/WebP/SVG/ICO/GIF를 128px 정적 PNG로 변환. `{id,icon:upload:UUID,...}` 반환 |
| `/api/uploaded-icons/{id}/content` | GET | 소유자 또는 허용된 공개 링크 사용자만 PNG 조회. private/no-cache, ETag/304; 권한 검사는 304보다 먼저 수행 |
| `/api/uploaded-icons/{id}` | DELETE | 본인 미사용 아이콘 삭제. 북마크·공개 링크·휴지통 참조 시 409. 실제 S3 삭제는 영속 예약으로 재시도 |

`upload:UUID`는 북마크·다중 편집·공개 링크의 `icon`에 사용할 수 있습니다. 지정할 때도 파일 사용 권한을 확인합니다. 변환은 한 번에 하나의 별도 프로세스에서 메모리 256MiB·최대 10초로 제한하고 SVG의 외부 리소스와 XML 엔티티를 차단합니다. 아이콘은 계정별 100개·파일별 96KiB 이하, 서버 전체 128MiB로 제한하며 계정/IP별 업로드 시도는 15분에 10회입니다. 원본 해상도는 각 변 8192픽셀·총 1677만 픽셀 이하입니다. 백업의 `icons` 목록에는 이름·파일 본문과 참조 키를 보관하며 복원 시 소유 계정에 맞는 ID로 다시 연결합니다. 기존 아이콘 목록과 이전 버전의 백업 가져오기도 유지합니다.

북마크 응답의 `managed=true`는 공개 목록에서 추가한 항목입니다. 공개 해제 시 포털 결과에서 제외하고 개별 조회·수정은 404입니다. 항목 삭제는 가능하며 재공개 시 삭제하지 않은 배치가 복원됩니다. 관리 항목의 URL 변경은 409이고 이름·아이콘·색상·카테고리 편집은 허용합니다. 일반 북마크는 별도로 동작합니다.

## 정렬·검색 제안

| 경로 | 메서드 | 설명 |
| --- | --- | --- |
| `/api/reorder` | POST | 로그인 사용자; `kind=tabs/categories/bookmarks`, `parent_id`(탭 정렬은 null), 전체 visible `ids`; 중복 422, 목록 불일치 409, 타 사용자 부모 404; 한 트랜잭션으로 순서 저장 |
| `/api/search/suggestions` | POST | 로그인 사용자 + 변경 헤더; `query` 최대 120자, `provider=g|d|y`(기본 g); `suggestions,available` 반환. Google·DuckDuckGo·Yandex 중 선택한 고정 제공자만 호출하며 사용자별 예산·짧은 메모리 캐시·연결/전체 타임아웃 적용 |

검색 제안은 사용자가 켠 경우에만 프런트에서 호출합니다. 주소 형식은 외부로 전달하지 않습니다. 외부 장애·응답 형식 오류·요청 예산 초과 시 200과 `available=false`로 로컬 검색을 유지하고 정상 검색이 NPG 실패 코드로 집계되지 않게 합니다. 인증 실패는 기존대로 401입니다. 북마크 검색은 현재 사용자의 `/api/portal` 결과 안에서 수행하므로 별도 외부 조회가 없습니다. 공개 해제된 구독은 정렬에서 제외하고 복원될 때 기존 visible 순서 뒤에 배치합니다.

## 직접 등록 API와 날씨

`provider=custom`이면 `custom_api` 객체를 지정합니다: `endpoint`(같은 서버의 상대 GET 경로), `items_path`(배열 경로, 최상위면 빈 문자열), `url_field`(URL/도메인 필드 또는 문자열 배열이면 빈 문자열), `name_field`(선택), `url_format=url|domain`, `auth_type=bearer|header|none`, `auth_header`(기본 X-API-Key). 필드 경로는 점으로 구분하며 배열 인덱스도 지원합니다. 인증 방식이나 헤더·주소를 바꾸면 토큰을 다시 입력해야 합니다. 인증 없음으로 변경하면 기존 암호화 토큰을 삭제합니다. 코드 실행·자동 로그인·다중 페이지 호출은 지원하지 않습니다.

`GET /api/weather`는 로그인 사용자가 저장된 포털 위치·온도 단위의 현재 기온을 조회합니다. `available,location,scale,provider`와 성공 시 `temperature,resolved_location,observed_at`, 실패 시 `message`를 반환합니다. 공급자 장애도 200과 `available=false`로 반환합니다. 인증 실패와 구분하며 공급자 오류 본문은 노출하지 않습니다. 성공은 10분, 실패는 1분 동안 서버 메모리에 저장합니다.

## 시계·자동완성 제공자

포털 설정의 `clock_format`은 `12h` 또는 `24h`(기본)이며 `/api/portal`의 `clock.format`에 저장됩니다. 날짜·시계에 `clock.timezone`을 함께 사용하고 보조 시계는 표시하지 않습니다. Yandex 검색 엔진 키는 `y`입니다.

`POST /api/search/suggestions`는 `{"query":"한글 검색","provider":"d"}` 형식으로 Google(`g`), DuckDuckGo(`d`), Yandex(`y`) 중 하나의 고정 HTTPS 서비스로 전달합니다. 생략 시 기존처럼 Google을 사용합니다. 제공자 URL 입력은 허용하지 않으며 요청·응답 크기, 시간 제한, 사용자별 공통 요청 한도와 주소 형식 제외를 유지합니다. 캐시는 사용자·제공자·검색어로 분리합니다. 지원하는 JSON 배열을 읽고 공급자 장애·과도한 요청은 200과 `available=false`로 반환합니다. 정상적인 빈 결과는 `available=true,suggestions=[]`입니다.

## 구성 백업·휴지통

모든 변경 요청은 기존과 같이 로그인 세션과 `X-CatppuccinDock: 1`이 필요합니다. 개인 데이터는 세션 사용자에게만 적용됩니다.

- `POST /api/backups/export`: `{ encrypted, password, include_images, include_settings }` → JSON 첨부 파일. 공통 검색·시계·날씨 설정 포함은 관리자만 가능. 계정·인증정보·공유 원본/권한·모니터링 구성 제외.
- `POST /api/backups/import-preview`: `{ document, password }` → 10분간 유효한 사용자별 `preview_id`와 미리 보기. 암호 오류는 422.
- `POST /api/backups/import`: `{ preview_id, mode: "merge"|"replace", apply_settings }` → 추가/중복/권한 제외 개수와 `undo_id`. 미리 보기 이후 편집했거나 이미 사용한 ID는 409.
- `POST /api/browser-bookmarks/preview`: `{ html }` → 선택 가능한 항목과 `preview_id`.
- `POST /api/browser-bookmarks/import`: `{ preview_id, selected_ids }` → HTTP/HTTPS 북마크 선택 가져오기.
- `GET /api/browser-bookmarks/export`: 브라우저용 HTML 첨부 파일.
- `GET /api/trash`: 본인의 30일/100건 기록 메타데이터.
- `POST /api/trash/{id}/restore`: 삭제 복원 또는 순서·덮어쓰기 되돌리기. 충돌은 409.
- `DELETE /api/trash/{id}`: 본인 기록 영구 삭제.

## 그룹·공개 링크 접근

- 관리자 `GET/POST /api/admin/groups`, `PUT/DELETE /api/admin/groups/{id}`: `{ name, user_ids }`.
- 관리자 `PUT /api/admin/library/{id}`에 `access_mode: "all"|"restricted"`, `user_ids`, `group_ids`를 지원. 생략한 접근 모드는 기존 권한을 유지. restricted에서 아무도 지정하지 않으면 관리자만 접근 가능.
- 일반 공개 링크·메인·검색·북마크 수정·공유 추가·백업은 현재의 게시 여부와 사용자/그룹 권한을 함께 검사.

## 상태 확인·프록시 변경 감지

- 관리자 `GET/POST /api/admin/monitors`, `PUT/DELETE /api/admin/monitors/{id}`: `{ name, link_url, check_url, allow_private, enabled, interval }`.
- 관리자 `POST /api/admin/monitors/{id}/check`: 명시적 확인. 상태는 `up/down/pending`. 401/403과 로그인 경로 응답은 up이며 이전 auth 기록도 up으로 반환합니다.
- `GET /api/bookmark-status`: 현재 사용자에게 보이는 북마크 ID별 상태만 반환. 내부 상태 확인 URL은 제외.
- 관리자 `GET/PUT /api/admin/proxy-sources/{id}/sync`: `{ enabled, interval, scheme, public_port }`.
- 관리자 `POST /api/admin/proxy-sources/{id}/sync/check`: 최신 인벤토리와 승인 대기 변경 조회.
- 관리자 `POST /api/admin/proxy-sources/{id}/sync/review`: `{ revision, change_ids, action: "apply"|"ignore" }`. 선택한 변경만 반영/확인. 이전 revision은 409.

## 하단바·외부 수치

- `GET /api/footer`: 사용자에게 허용된 `order/hidden/metrics`. 일반 사용자에게 API 주소·쿼리·토큰은 반환하지 않음.
- `PUT /api/footer/order`: `{ order }` 개인 순서 저장. 현재 허용된 모든 ID를 중복 없이 포함해야 하며 다른 항목·숨김 설정은 거절.
- `DELETE /api/footer/order`: 개인 순서 초기화.
- 관리자 `GET/PUT /api/admin/footer`: `{ order, hidden }` 공통 구성. edit(화면 순서 편집 버튼)도 순서·숨김 설정 가능하며 settings/logout 숨김 및 필수 항목 누락은 422.
- 관리자 `POST /api/admin/footer/metrics`, `PUT/DELETE /api/admin/footer/metrics/{id}`: 모니터링 위젯 등록·수정·삭제.
- 관리자 `POST /api/admin/footer/metrics/{id}/check`: 15초 제한으로 즉시 조회. 새 설정은 이전 응답을 무효화.

위젯 등록 필드: `name`, `provider: prometheus|grafana|kuma`, `base_url`, 선택적 `token/clear_token`, `query`, `datasource_uid`, `slug`, `monitor_id`, `metric: status|latency|uptime`, `display: value|sparkline|status`, `unit`, `interval`(60..86400초), `window`(300..86400초), `allow_private`, `enabled`, `audience: admin|all`(기본 admin). 최대 24개. Grafana는 Prometheus 데이터 소스만 지원. Kuma는 게시된 상태 페이지의 모니터만 지원.

외부 응답은 2MB로 제한하며 DNS 결과를 검증하고 연결 IP를 고정합니다. 내부 주소는 별도 허용, 루프백·링크 로컬·메타데이터 주소 차단, TLS 검증, 리다이렉트 차단을 적용합니다. Bearer 토큰은 암호화하여 서버에만 저장하고 주소 변경 시 제거합니다. 공개 응답은 수치·최대 120개 그래프 점·상태로 제한합니다.

- `POST /api/weather/refresh`: 현재 설정한 위치의 수동 갱신. 10분 캐시를 우회하지만 위치/단위별로 1분 이내 조회가 있으면 재사용.

## 설정 메뉴 개인 순서

- `GET /api/navigation`: 현재 계정의 설정 메뉴 순서. 현재 권한으로 볼 수 없는 메뉴는 제외하고 새 메뉴는 끝에 추가합니다.
- `PUT /api/navigation`: `{ order: [메뉴 ID, ...] }`. 로그인 사용자 본인의 순서만 저장하며 현재 허용된 전체 ID를 중복 없이 포함해야 합니다. 다른 사용자 지정이나 메뉴 숨김은 지원하지 않습니다. 구성 불일치는 409.
- `DELETE /api/navigation`: 본인 메뉴 순서를 기본값으로 복원합니다. 변경 요청에는 기존 변경 헤더가 필요합니다.

### 상태 확인 일괄 작업

- 관리자 `POST /api/admin/monitors/bulk`: `{ bookmark_ids, interval: 300, allow_private: false }`. 본인의 현재 보이는 북마크를 최대 200개 선택해 등록합니다. URL을 확인 주소로 사용하고 현재 공유 URL을 해석합니다. 같은 URL·기존 대상은 건너뛰며 기존의 내부 확인 주소·활성 여부·간격을 덮어쓰지 않습니다. 소유권·공개 권한·URL·최대 대상 수 검증에 실패하면 전체 작업을 취소합니다. 응답은 `{ added, duplicates }`.
- 관리자 `POST /api/admin/monitors/check-all`: 활성 대상의 재확인을 예약하고 서버에서 최대 4개씩 확인합니다. 최근 15초 내 확인한 대상은 제외하며 전체 요청에도 15초 제한이 있습니다. 응답 `{ queued_ids, skipped, requested_at }` 이후 관리자 목록의 `checked_at`으로 진행률을 표시합니다. 비활성 대상은 요청하지 않습니다. 대기 작업의 `next_check=0`은 DB에 저장되므로 재시작 시 주기 작업도 처리할 수 있습니다.
- 401·403 및 로그인 경로 응답은 `up`으로 표시합니다. 401·403 응답의 자동 재확인은 반복 인증 실패 요청을 줄이기 위해 하루 동안 유예하며 관리자 수동 확인으로 다시 확인할 수 있습니다.

웹 검색의 열기 방식은 `search_open_mode`로 저장하며 `/api/portal`의 `search.openMode`로 전달합니다. 기본은 `same_tab`이며 `new_tab`은 웹 검색·검색 엔진 바로가기·자동완성에 적용합니다. 구성 백업에도 포함합니다. 설정 메뉴는 프런트에서 기능별 그룹으로 표시하지만 `/api/navigation`은 각 계정이 접근할 수 있는 세부 화면 ID 순서를 계속 저장합니다. `sso` 화면은 관리자만 사용할 수 있습니다.

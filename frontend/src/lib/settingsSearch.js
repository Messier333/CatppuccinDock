const topics = {
  proxmox: [['내 Proxmox 연결·패널·제어', 'API 토큰을 연결하고 북마크 요약·상세 패널과 VM·LXC 제어를 설정합니다.', '홈랩 서버 노드 api 스냅샷 백업 복제 이동 메모리 cpu 권한 드래그', 'proxmox']],
  sso: [['SSO·로그인 허용 방식', 'OIDC 인증 서비스를 등록하고 SSO 전용 로그인 여부를 정합니다.', '로그인 인증 authentik keycloak issuer client secret 비밀번호 sso만', 'sso']],
  bookmarks: [
    ['북마크 다중 선택·중복 정리', '선택한 링크를 이동하거나 아이콘 변경·삭제합니다.', '일괄 대량 중복 url 이동 편집 삭제', 'bulk'],
    ['북마크 추가·편집·순서 변경', '탭과 카테고리별 링크를 관리합니다.', '링크 주소 이름 드래그 정렬 세부카테고리'],
    ['북마크 아이콘·GIF 배경', '북마크 아이콘을 검색·업로드하고 탭의 GIF를 설정합니다.', '아이콘 색상 검색 직접 업로드 png jpg svg ico webp 배너 배경 이미지 gif 위키미디어 openverse alphacoders motionbgs 픽셀 도시 자연 풍경 다운로드 저장'],
  ],
  preferences: [
    ['개인별 검색·날씨·시간 설정','내 계정의 검색 엔진·지역·시간대를 설정합니다.','기본값 사용자 개인 설정','personal'],
    ['내 슬라이드 효과','기기 설정 따르기·항상 켜기·끄기를 내 계정에 적용합니다.','좌우 슬라이드 슬라이딩 전환 이동 움직임 animation motion 동작 줄이기','personal-animation'],
    ['크롬 앱 설치','포털을 독립된 앱 창으로 설치합니다.','pwa chrome 크롬 애플리케이션 설치','install'],
  ],
  library: [['허용된 공개 링크 추가', '공개 목록에서 원하는 링크를 선택해 내 메인에 추가합니다.', '공유 링크 카테고리 선택']],
  backup: [
    ['암호화 백업 내보내기', '북마크·GIF·포털 설정을 JSON 파일로 저장합니다.', 'export json 암호 비밀번호 저장 다운로드'],
    ['백업 복원·브라우저 북마크 가져오기', 'JSON 백업 또는 Chrome·Firefox HTML 파일을 가져옵니다.', 'import 복구 업로드 파일 병합 덮어쓰기'],
  ],
  trash: [['삭제한 항목·순서 복원', '휴지통에서 삭제한 링크나 이전 구성을 복원합니다.', '되돌리기 실행 취소 복구']],
  security: [
    ['로그인 기기 관리', '접속 기기·IP·최근 활동을 확인하고 다른 기기를 로그아웃합니다.', '세션 접속 기록 브라우저 원격 로그아웃 로그인 기기관리', 'sessions'],
    ['2단계 인증·복구 코드', '인증 앱 연결과 일회용 복구 코드를 관리합니다.', '2fa totp otp mfa 보안'],
    ['비밀번호 변경', '현재 계정의 로그인 비밀번호를 변경합니다.', '패스워드 암호 계정'],
  ],
  backgrounds: [['GIF 검색 제공처·API 키', 'GIFDB·Pixabay 등 배경 제공처를 관리합니다.', 'gif 배경 통합 검색 pixabay gifdb api 키 등록', 'gif-providers'],['GIF 추가·다운로드 한도', '일반 사용자와 서버의 다운로드·업로드 횟수와 용량을 제한합니다.', '일반 사용자 악용 방지 제한 일일 횟수 업로드 저장 용량', 'gif-member-limits']],
  groups: [['그룹·소속 사용자 관리', '그룹에 사용자를 배정해 공개 링크 접근 권한을 관리합니다.', '팀 멤버 권한 공유']],
  footer: [
    ['하단바 표시·순서·메인 편집', '하단바 항목을 숨기거나 드래그로 순서를 변경합니다.', '하단 푸터 위치 화면 편집 설정 로그아웃', 'footer-layout'],
    ['서버 모니터링 위젯', 'Prometheus·Grafana·Uptime Kuma 수치와 그래프를 표시합니다.', 'cpu 메모리 서버 상태 프로메테우스 그라파나 쿠마 그래프', 'footer-widgets'],
  ],
  monitoring: [['북마크 서비스 상태 확인', '상태 도트를 설정하고 여러 링크를 등록하거나 전체 확인합니다.', '헬스체크 health check 온라인 도트 일괄 상태확인 주기 간격']],
  sync: [['프록시 변경 감지·승인', '리버스 프록시의 신규·삭제 변경을 확인하고 반영합니다.', '자동 동기화 주기 npm npg zoraxy']],
  users: [['사용자 추가·권한·SSO 연결', '일반 계정과 OIDC 계정을 추가하고 역할을 설정합니다.', '계정 로그인 비밀번호 관리자 일반 사용자 활성화']],
  import: [['서비스 API 등록·링크 가져오기', 'NPM·NPG·Zoraxy 또는 사용자 정의 API를 연결합니다.', '리버스 프록시 서비스 추가 사용자정의 토큰 json url']],
  shared: [['공개 링크 허용·대상 지정', '관리자가 가져온 링크를 선택한 사용자·그룹에 공개합니다.', '공유 허용 권한 게시 비공개 아이콘']],
  settings: [
    ['즐겨찾기·최근 사용 표시', '아이콘과 이름을 함께 표시하거나 아이콘만 표시합니다.', '북마크 즐겨찾기 최근사용 이름 숨기기 표시 아이콘만', 'bookmark-shelf'],
    ['시계 형식·시간대', '12시간 AM/PM 또는 24시간 형식과 시간대를 설정합니다.', '날짜 시간 캘린더 달력 timezone', 'clock'],
    ['날씨·위치·온도 단위', '지역과 섭씨·화씨 표시를 설정합니다.', '도시 위치 날씨 온도 c f', 'weather'],
    ['웹 검색 결과 열기', '검색 결과를 새 탭 또는 현재 탭에서 엽니다.', '구글 포털 검색 새창 새탭 현재창 현재탭 자동완성 열기', 'search-window'],
    ['기본 검색 엔진', 'Google·DuckDuckGo·Yandex 등 기본 검색을 선택합니다.', '구글 덕덕고 얀덱스 자동완성 perplexity', 'search'],

  ],
};

export function searchSettings(sections, query) {
  const terms = query.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  return sections.flatMap(section => (topics[section.id] || [[section.name, '설정을 엽니다.', '']])
    .map(([title, description, keywords, anchor]) => ({ section: section.id, sectionName: section.name, title, description, anchor, keywords })))
    .filter(item => terms.every(term => `${item.sectionName} ${item.title} ${item.description} ${item.keywords}`.normalize('NFKC').toLocaleLowerCase().includes(term)));
}

"""Display labels for browser sessions; never expose authentication tokens/hashes."""


def device_details(user_agent):
    ua = user_agent.lower()
    if 'ipad' in ua or ('macintosh' in ua and 'mobile/' in ua):
        system, kind = 'iPadOS', 'tablet'
    elif 'iphone' in ua or 'ipod' in ua:
        system, kind = 'iOS', 'mobile'
    elif 'android' in ua:
        system, kind = 'Android', 'mobile' if 'mobile' in ua else 'tablet'
    elif 'windows' in ua:
        system, kind = 'Windows', 'desktop'
    elif 'cros' in ua:
        system, kind = 'ChromeOS', 'desktop'
    elif 'macintosh' in ua or 'mac os x' in ua:
        system, kind = 'macOS', 'desktop'
    elif 'linux' in ua:
        system, kind = 'Linux', 'desktop'
    else:
        system, kind = '', 'unknown'
    browser = next((label for signatures, label in (
        (('edg/', 'edga/', 'edgios/'), 'Edge'),
        (('opr/', 'opera/'), 'Opera'),
        (('samsungbrowser/',), 'Samsung Internet'),
        (('firefox/', 'fxios/'), 'Firefox'),
        (('chrome/', 'crios/'), 'Chrome'),
        (('safari/',), 'Safari'),
    ) if any(signature in ua for signature in signatures)), '')
    return {'label': ' · '.join(value for value in (browser, system) if value) or '기기 정보 없음', 'kind': kind}


def session_details(session):
    return {'id': session.public_id, **device_details(session.user_agent),
            'ip_address': session.ip_address, 'created_at': session.created_at,
            'last_seen_at': session.last_seen_at, 'expires_at': session.expires_at}

"""Local OpenID provider fixture: real discovery, PKCE and RSA-signed ID tokens."""
import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from joserfc import jwt
from joserfc.jwk import RSAKey


class Provider:
    def __init__(self):
        self.key = RSAKey.generate_key(2048)
        self.other_key = RSAKey.generate_key(2048)
        self.codes = {}
        self.claim_overrides = {}
        self.bad_signature = False
        self.subject = 'external-user-123'
        self.pkce_verified = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_json(self, body, status=200):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == '/.well-known/openid-configuration':
                    self.send_json({'issuer': owner.issuer, 'authorization_endpoint': owner.issuer+'/authorize',
                        'token_endpoint': owner.issuer+'/token', 'jwks_uri': owner.issuer+'/jwks',
                        'response_types_supported': ['code'], 'subject_types_supported': ['public'],
                        'id_token_signing_alg_values_supported': ['RS256'],
                        'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['client_secret_basic']})
                elif path == '/jwks':
                    key = owner.key.as_dict(private=False)
                    key['kid'] = 'test-key'
                    self.send_json({'keys': [key]})
                elif path == '/authorize':
                    query = parse_qs(urlsplit(self.path).query)
                    code = owner.issue_code(query)
                    self.send_response(302)
                    self.send_header('Location', query['redirect_uri'][0]+'?'+urlencode({'code':code,'state':query['state'][0]}))
                    self.end_headers()
                else:
                    self.send_json({'error':'not_found'},404)

            def do_POST(self):
                if self.path != '/token':
                    self.send_json({'error':'not_found'},404)
                    return
                query = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                data = owner.codes.pop(query.get('code',[''])[0],None)
                expected_auth = 'Basic '+base64.b64encode(b'test-client:test-secret').decode()
                if not data or self.headers.get('Authorization') != expected_auth:
                    self.send_json({'error':'invalid_grant'},400)
                    return
                verifier = query.get('code_verifier',[''])[0]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                if not verifier or challenge != data.get('code_challenge',[''])[0] or query.get('redirect_uri') != data.get('redirect_uri'):
                    self.send_json({'error':'invalid_grant'},400)
                    return
                owner.pkce_verified = True
                now = int(time.time())
                claims = {'iss':owner.issuer,'sub':owner.subject,'aud':'test-client','iat':now,'exp':now+300,'nonce':data['nonce'][0],
                          'preferred_username':'test-owner','email':'test-owner@example.test','email_verified':True}
                claims.update(owner.claim_overrides)
                key = owner.other_key if owner.bad_signature else owner.key
                encoded = jwt.encode({'alg':'RS256','kid':'test-key'},claims,key)
                self.send_json({'access_token':secrets.token_urlsafe(24),'token_type':'Bearer','expires_in':300,'id_token':encoded})

        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.issuer = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def issue_code(self, query):
        code = secrets.token_urlsafe(24)
        self.codes[code] = query
        return code

    def close(self):
        self.server.shutdown()
        self.server.server_close()

import { test, expect } from '@playwright/test';

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const headers = { 'X-CatppuccinDock': '1' };

async function login(page) {
  await page.goto('/');
  await page.getByLabel('아이디', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('link', { name: '설정', exact: true })).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  const health = await request.get('/api/health');
  expect(await health.json()).toMatchObject({ status: 'ok', database: 'ok', storage: 's3' });
  const status = await request.get('/api/auth/status');
  if ((await status.json()).setup_required) {
    const setup = await request.post('/api/auth/setup', {
      headers, data: { username, password, setup_code: process.env.E2E_SETUP_CODE },
    });
    expect(setup.status()).toBe(200);
  } else {
    // Playwright restarts a worker after a failure; reuse only this stack's fixture owner.
    expect((await request.post('/api/auth/login', { headers, data: { username, password } })).status()).toBe(200);
  }
});

test.beforeEach(async ({ page }) => {
  // Only optional external data is stubbed. Auth, bookmarks, media and S3 use real services.
  await page.route('**/api/weather**', route => route.fulfill({ json: { available: false } }));
  await page.route('**/api/bookmark-tools/preview', route => route.fulfill({
    json: { name: 'Browser bookmark', icon: 'world', notice: '테스트 미리보기' },
  }));
});

test('login rejects a wrong password, accepts the owner and logout revokes access', async ({ page }) => {
  expect((await page.request.get('/api/portal')).status()).toBe(401);
  await page.goto('/');
  await page.getByLabel('아이디', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill('incorrect-browser-password');
  const failure = page.waitForResponse(response => response.url().endsWith('/api/auth/login'));
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  expect((await failure).status()).toBe(401);
  await expect(page.getByRole('alert')).toBeVisible();
  await login(page);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
  expect((await page.request.get('/api/portal')).status()).toBe(401);
});

test('quick-add saves a bookmark and it survives a full page reload', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: '화면 순서 편집', exact: true }).click();
  await page.getByRole('button', { name: '북마크 빠른 추가', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '북마크 빠른 추가', exact: true });
  await dialog.getByLabel('북마크 URL', { exact: true }).fill('https://bookmark.example.test/browser');
  await expect(dialog.getByText('테스트 미리보기', { exact: true })).toBeVisible();
  await dialog.getByLabel('북마크 이름', { exact: true }).fill('E2E 북마크');
  await dialog.getByRole('button', { name: '북마크 저장', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: '화면 편집 완료', exact: true }).click();
  const bookmark = page.getByRole('link', { name: 'E2E 북마크', exact: true });
  await expect(bookmark).toHaveAttribute('href', 'https://bookmark.example.test/browser');
  await page.reload();
  await expect(bookmark).toBeVisible();
});

test('uploaded GIF is stored in Garage and displayed as a new tab background', async ({ page }) => {
  await login(page);
  await page.getByRole('link', { name: '설정', exact: true }).click();
  await page.getByRole('button', { name: '탭 추가', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('이름', { exact: true }).fill('E2E GIF');
  // A tiny valid GIF is sufficient to exercise browser upload and the real media/S3 path.
  const gif = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAAAAAAALAAAAAABAAEAAAIBRAA7', 'base64');
  await dialog.getByLabel('GIF 파일 선택', { exact: true }).setInputFiles({
    name: 'browser-fixture.gif', mimeType: 'image/gif', buffer: gif,
  });
  await expect(dialog.getByText('GIF를 선택했어요. 아래 저장 버튼을 누르면 메인에 적용됩니다.', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '저장', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const portal = await (await page.request.get('/api/portal')).json();
  const tab = portal.tabs.find(item => item.name === 'E2E GIF');
  expect(tab.background_id).toBeTruthy();
  const mediaPath = `/api/backgrounds/${tab.background_id}/content`;
  const media = await page.request.get(mediaPath);
  expect(media.status()).toBe(200);
  expect(media.headers()['content-type']).toContain('image/gif');
  expect(await media.body()).toEqual(gif);
  await page.goto('/');
  await page.getByRole('button', { name: 'E2E GIF 탭', exact: true }).click();
  const art = page.locator('.startpage-art');
  await expect(art).toHaveCSS('background-image', new RegExp(tab.background_id));
});

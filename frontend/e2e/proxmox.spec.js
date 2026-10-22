import { test, expect } from '@playwright/test';

const headers = { 'X-CatppuccinDock':'1' };
const root = '/api/integrations/proxmox';
const credentials = {username:process.env.E2E_USERNAME,password:process.env.E2E_PASSWORD};
const fixtureData = {
  summary: { guests:{value:1,total:2},nodes:{value:1,total:1},cpu:25,memory:50,storage:25 },
  nodes:[{id:'node/pve1',type:'node',node:'pve1',name:'pve1',status:'online',cpu:.25,maxcpu:16,mem:8*1024**3,maxmem:16*1024**3,actions:[]}],
  guests:[{id:'qemu/100',type:'qemu',node:'pve1',vmid:100,name:'Media VM',status:'running',cpu:.1,mem:1024**3,maxmem:4*1024**3,disk:10,maxdisk:100,uptime:3600,actions:['shutdown','snapshot']}],
  storage:[{id:'storage/pve1/local',type:'storage',node:'pve1',storage:'local',disk:25*1024**3,maxdisk:100*1024**3}],
};

let sessionCookies;
test.beforeAll(async ({request}) => {
  const state = await (await request.get('/api/auth/status')).json();
  const response = await request.post(state.setup_required ? '/api/auth/setup' : '/api/auth/login', {headers,data:state.setup_required ? {...credentials,setup_code:process.env.E2E_SETUP_CODE} : credentials});
  expect(response.status()).toBe(200);
  sessionCookies = (await request.storageState()).cookies;
});

let bookmark, connectionIds, pageErrors, operations;
test.beforeEach(async ({page},testInfo) => {
  connectionIds = []; pageErrors = []; operations = []; bookmark = null;
  page.on('pageerror',error => pageErrors.push(error.message));
  await page.context().addCookies(sessionCookies);
  const portal = await (await page.request.get('/api/portal')).json();
  const response = await page.request.post('/api/bookmarks',{headers,data:{name:`PVE ${testInfo.workerIndex} ${testInfo.line}`,url:'https://pve.example.test:8006',category_id:portal.tabs[0].categories[0].id,icon:'server'}});
  expect(response.status()).toBe(200); bookmark = await response.json();
  await page.route('**/api/weather**',route => route.fulfill({json:{available:false}}));
  // Stub only the remote inventory/control exchange. Connection settings,
  // ownership, bookmark bindings and layout persistence use the real backend.
  await page.route('**/api/integrations/proxmox/**',async route => {
    const path = new URL(route.request().url()).pathname;
    const id = path.split('/')[4];
    if (path.endsWith('/refresh') && !path.includes('/tasks/')) {
      const rows = (await (await page.request.get(root)).json()).integrations;
      const row = rows.find(item => item.id === id);
      if (!connectionIds.includes(id)) connectionIds.push(id);
      return route.fulfill({json:{...row,data:fixtureData,checked_at:Date.now()/1000,next_check:Date.now()/1000+60,error:''}});
    }
    if (path.endsWith('/resource')) {
      return route.fulfill({json:{resource:fixtureData.guests[0],snapshots:[{name:'before'}],actions:['shutdown','snapshot']}});
    }
    if (path.endsWith('/intents')) {
      operations.push(route.request().postDataJSON());
      return route.fulfill({json:{intent:'b'.repeat(48),label:'정상 종료',target:'Media VM',confirmation:'100',dangerous:false,parameters:{},expires_in:120}});
    }
    if (path.endsWith('/execute')) {
      operations.push(route.request().postDataJSON());
      return route.fulfill({json:{id:'fixture-task',state:'running',detail:''}});
    }
    await route.continue();
  });
});

test.afterEach(async ({page}) => {
  for (const id of connectionIds) await page.request.delete(`${root}/${id}`,{headers});
  if (bookmark?.id) await page.request.delete(`/api/bookmarks/${bookmark.id}`,{headers});
  expect(pageErrors).toEqual([]);
});

async function seed(page) {
  const response = await page.request.post(root,{headers,data:{name:'Browser PVE',base_url:'https://pve.example.test:8006',token_id:'dock@pve!browser',token:'browser-fixture-token',controls:true,bookmark_ids:[bookmark.id]}});
  expect(response.status()).toBe(200);
  const row = await response.json();connectionIds.push(row.id);return row;
}

async function panel(page) {
  await page.goto('/');
  await page.getByRole('button',{name:'Browser PVE Proxmox 상세 정보 열기',exact:true}).click();
  const dialog = page.getByRole('dialog',{name:'Browser PVE',exact:true});
  await expect(dialog.getByRole('button',{name:'Media VM',exact:false})).toBeVisible();
  return dialog;
}

test('connection editor saves private bindings and renders a separate badge without changing the panel ratio',async ({page}) => {
  await page.goto('/admin/?section=proxmox');
  await page.getByRole('button',{name:'Proxmox 추가',exact:true}).click();
  const editor = page.getByRole('dialog',{name:'Proxmox 추가',exact:true});
  await editor.getByLabel('이름',{exact:true}).fill('Browser PVE');
  await editor.getByLabel('Proxmox 주소',{exact:true}).fill('https://pve.example.test:8006');
  await editor.getByLabel('API Token ID',{exact:true}).fill('dock@pve!browser');
  await editor.getByLabel('Token Secret',{exact:true}).fill('browser-fixture-token');
  await editor.getByLabel('서버 제어 허용',{exact:true}).check();
  await editor.getByLabel(bookmark.name,{exact:false}).check();
  await editor.getByRole('button',{name:'저장 · 연결 확인',exact:true}).click();
  await expect(editor).not.toBeVisible();
  await expect(page.getByText('연결 확인됨',{exact:false})).toBeVisible();
  const dialog = await panel(page);
  await expect(dialog.getByText('1/2 가동',{exact:true})).toBeVisible();
  await dialog.getByRole('button',{name:'Proxmox 패널 닫기',exact:true}).click();
  await expect(page.getByRole('link',{name:bookmark.name,exact:true})).toHaveAttribute('href','https://pve.example.test:8006/');
  const ratio = await page.locator('.startpage-panel').evaluate(element => element.clientWidth/element.clientHeight);
  expect(Math.abs(ratio-8/3)).toBeLessThan(.05);
});

test('drawer cards reorder by drag and keyboard and persist widths visibility and metrics',async ({page}) => {
  const row = await seed(page), dialog = await panel(page);
  await dialog.getByRole('button',{name:'상세 패널 편집',exact:true}).click();
  const cards = dialog.locator('.pve-panel-sections>[data-sort-id]');
  const from = await cards.nth(0).locator('.reorder-handle').boundingBox();
  const to = await cards.nth(1).boundingBox();
  await page.mouse.move(from.x+from.width/2,from.y+from.height/2);
  await page.mouse.down();await page.mouse.move(to.x+to.width/2,to.y+to.height-5,{steps:16});await page.mouse.up();
  await expect(cards.nth(0)).toHaveAttribute('data-sort-id','nodes');
  await cards.nth(0).locator('.reorder-handle').press('ArrowDown');
  await expect(cards.nth(0)).toHaveAttribute('data-sort-id','overview');
  await cards.nth(0).locator('.reorder-handle').press('ArrowDown');
  const nodes = dialog.locator('[data-sort-id=nodes]');
  await nodes.getByRole('combobox',{name:'노드 카드 너비',exact:true}).click();
  await page.getByRole('option',{name:'절반 너비',exact:true}).click();
  await dialog.getByLabel('CPU',{exact:true}).first().check();
  const storage = dialog.locator('[data-sort-id=storage]');
  await storage.getByLabel('표시',{exact:true}).uncheck();
  await dialog.getByRole('button',{name:'구성 저장',exact:true}).click();
  await expect(dialog.getByText('패널 구성을 저장했어요.',{exact:true})).toBeVisible();
  const saved = (await (await page.request.get(root)).json()).integrations.find(item => item.id === row.id);
  expect(saved.config.sections.find(section => section.id === 'storage').visible).toBe(false);
  expect(saved.config.sections[0].id).toBe('nodes');
  expect(saved.config.sections[0].width).toBe('half');
  expect(saved.config.metrics).toContain('cpu');
  await page.reload();
  await page.getByRole('button',{name:'Browser PVE Proxmox 상세 정보 열기',exact:true}).click();
  await expect(page.locator('.pve-drawer [data-sort-id=storage]')).toHaveCount(0);
});

test('resource menu shows only offered actions and requires target confirmation before any control',async ({page}) => {
  await seed(page);const dialog = await panel(page);
  await dialog.getByRole('button',{name:'Media VM',exact:false}).click();
  const control = dialog.getByRole('region',{name:'리소스 관리',exact:true});
  await control.getByRole('combobox',{name:'Proxmox 작업',exact:true}).click();
  await expect(page.getByRole('option',{name:'강제 중지',exact:true})).toHaveCount(0);
  await page.getByRole('option',{name:'정상 종료',exact:true}).click();
  await control.getByRole('button',{name:'작업 확인',exact:true}).click();
  const run = control.getByRole('button',{name:'실행',exact:true});await expect(run).toBeDisabled();
  expect(operations).toHaveLength(1);
  await control.getByRole('textbox').fill('wrong');await expect(run).toBeDisabled();
  await control.getByRole('textbox').fill('100');await run.click();
  expect(operations).toHaveLength(2);
  expect(operations[0]).toEqual({resource:'qemu/100',action:'shutdown',parameters:{}});
  expect(operations[1].confirmation).toBe('100');
});

test('drawer fits mobile and backdrop text drag does not dismiss it',async ({page}) => {
  await seed(page);const dialog = await panel(page);
  const title = await dialog.getByRole('heading',{name:'Browser PVE',exact:true}).boundingBox();
  await page.mouse.move(title.x+10,title.y+10);await page.mouse.down();await page.mouse.move(10,10);await page.mouse.up();
  await expect(dialog).toBeVisible();
  await page.mouse.click(10,10);await expect(dialog).not.toBeVisible();
  await page.setViewportSize({width:430,height:900});
  await page.getByRole('button',{name:'Browser PVE Proxmox 상세 정보 열기',exact:true}).click();
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();
});

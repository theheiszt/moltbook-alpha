const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const siteDir = 'I:\\Scripts and Programs\\moltbook-site';
const server = http.createServer((req, res) => {
  let filePath = path.join(siteDir, req.url.split('?')[0]);
  if (filePath.endsWith('\\')) filePath += 'index.html';
  if (!fs.existsSync(filePath)) { res.writeHead(404); return res.end('Not found'); }
  const ext = path.extname(filePath);
  const types = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png'
  };
  res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream' });
  fs.createReadStream(filePath).pipe(res);
});

server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  console.log('========================================================================');
  console.log('  MoltAlpha Immersive Landing Page & Mega-Menu CDP Test Suite');
  console.log('========================================================================');
  console.log('• Local HTTP test server running at http://127.0.0.1:' + port);

  const cdpPort = 9535;
  const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  const chrome = spawn(chromePath, [
    '--headless=new',
    '--remote-debugging-port=' + cdpPort,
    '--disable-gpu',
    '--no-sandbox',
    '--window-size=1440,900'
  ]);

  await new Promise(r => setTimeout(r, 1200));

  let passed = 0;
  let failed = 0;

  function assert(condition, testName, details = '') {
    if (condition) {
      console.log(`  ✓ PASS: ${testName} ${details ? '(' + details + ')' : ''}`);
      passed++;
    } else {
      console.error(`  ✗ FAIL: ${testName} ${details ? '(' + details + ')' : ''}`);
      failed++;
    }
  }

  try {
    const listRes = await fetch('http://127.0.0.1:' + cdpPort + '/json/list');
    const tabs = await listRes.json();
    const target = tabs.find(t => t.type === 'page') || tabs[0];
    const ws = new WebSocket(target.webSocketDebuggerUrl);

    let msgId = 1;
    const send = (method, params = {}) => new Promise((resolve) => {
      const id = msgId++;
      const handler = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id === id) {
          ws.removeEventListener('message', handler);
          resolve(msg.result);
        }
      };
      ws.addEventListener('message', handler);
      ws.send(JSON.stringify({ id, method, params }));
    });

    await new Promise(r => ws.addEventListener('open', r));
    await send('Page.enable');
    await send('DOM.enable');

    console.log('\nNavigating to: http://127.0.0.1:' + port + '/index.html');
    await send('Page.navigate', { url: 'http://127.0.0.1:' + port + '/index.html' });
    await new Promise(r => setTimeout(r, 1500));

    console.log('\n=== TIER 1: DOM Elements, Header & Mega-Menu Architecture ===');

    const evalResult = async (expr) => {
      const res = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
      return res.result ? res.result.value : null;
    };

    // Check Theme Stylesheet Link
    const hasThemeCss = await evalResult(`!!document.querySelector('link[href*="moltalpha-theme.css"]')`);
    assert(hasThemeCss, 'Theme stylesheet linked', 'moltalpha-theme.css');

    // Check Global Fixed Header
    const hasHeader = await evalResult(`!!document.querySelector('header.site-header')`);
    assert(hasHeader, 'Global fixed header present', '.site-header');

    // Check Mega-Menu Triggers
    const megaTriggersCount = await evalResult(`document.querySelectorAll('.nav-trigger').length`);
    assert(megaTriggersCount >= 2, 'Mega-menu triggers present', `${megaTriggersCount} triggers`);

    // Check Mobile Menu Toggle Button
    const hasMobileBtn = await evalResult(`!!document.getElementById('mobileMenuBtn')`);
    assert(hasMobileBtn, 'Mobile hamburger button present', '#mobileMenuBtn');

    // Check Hero Network Canvas
    const hasCanvas = await evalResult(`!!document.getElementById('heroNetworkCanvas')`);
    assert(hasCanvas, 'Hero financial network canvas present', '#heroNetworkCanvas');

    console.log('\n=== TIER 2: Sentinel 6-Stage Pinned Showcase Architecture ===');

    // Check Sentinel Section
    const hasSentinel = await evalResult(`!!document.getElementById('sentinel')`);
    assert(hasSentinel, 'Sentinel section container present', '#sentinel');

    // Check 6 Narrative Step Cards
    const stepCardsCount = await evalResult(`document.querySelectorAll('[data-showcase-step]').length`);
    assert(stepCardsCount === 6, 'All 6 narrative step cards present', `Found ${stepCardsCount}/6`);

    // Check 6 Pinned Showcase Frames
    const framesCount = await evalResult(`document.querySelectorAll('[data-showcase-frame]').length`);
    assert(framesCount === 6, 'All 6 showcase stage frames present', `Found ${framesCount}/6`);

    // Check 6 Screenshot Images Loaded
    const imagesLoaded = await evalResult(`
      (() => {
        const imgs = Array.from(document.querySelectorAll('[data-showcase-frame] img'));
        return imgs.every(img => img.getAttribute('src').startsWith('assets/sentinel-showcase/'));
      })()
    `);
    assert(imagesLoaded, 'All 6 stage frames reference genuine assets', 'assets/sentinel-showcase/*.png');

    // Check Interactive Stage Switcher Dots
    const dotsCount = await evalResult(`document.querySelectorAll('[data-dot]').length`);
    assert(dotsCount === 6, 'All 6 interactive stage dots present', `Found ${dotsCount}/6`);

    console.log('\n=== TIER 3: Interactive State Machine & Switcher Verification ===');

    // Test Clicking Dot 2 (Preflight)
    await evalResult(`jumpToShowcaseStage(2)`);
    await new Promise(r => setTimeout(r, 200));

    const step2Active = await evalResult(`document.querySelector('[data-showcase-step="2"]').classList.contains('active')`);
    const frame2Active = await evalResult(`document.querySelector('[data-showcase-frame="2"]').classList.contains('active')`);
    const routeText2 = await evalResult(`document.getElementById('showcaseTerminalRoute').innerText`);

    assert(step2Active, 'jumpToShowcaseStage(2) activates Step 2 narrative');
    assert(frame2Active, 'jumpToShowcaseStage(2) activates Frame 2 visual');
    assert(routeText2.includes('/risk'), 'Terminal title route updates to /risk', routeText2);

    // Test Clicking Dot 6 (Cryptographic Witness)
    await evalResult(`jumpToShowcaseStage(6)`);
    await new Promise(r => setTimeout(r, 200));

    const step6Active = await evalResult(`document.querySelector('[data-showcase-step="6"]').classList.contains('active')`);
    const frame6Active = await evalResult(`document.querySelector('[data-showcase-frame="6"]').classList.contains('active')`);
    const routeText6 = await evalResult(`document.getElementById('showcaseTerminalRoute').innerText`);

    assert(step6Active, 'jumpToShowcaseStage(6) activates Step 6 narrative');
    assert(frame6Active, 'jumpToShowcaseStage(6) activates Frame 6 visual');
    assert(routeText6.includes('public-key'), 'Terminal title route updates to public-key', routeText6);

    // Reset back to Step 1
    await evalResult(`jumpToShowcaseStage(1)`);

    console.log('\n=== TIER 4: Mobile Drawer Interactive Toggle ===');

    const drawerInitiallyHidden = await evalResult(`document.getElementById('mobileDrawer').classList.contains('hidden')`);
    assert(drawerInitiallyHidden, 'Mobile drawer initially closed/hidden');

    // Click toggle button
    await evalResult(`document.getElementById('mobileMenuBtn').click()`);
    const drawerOpen = await evalResult(`!document.getElementById('mobileDrawer').classList.contains('hidden')`);
    assert(drawerOpen, 'Clicking mobileMenuBtn opens drawer');

    // Press Escape key
    await evalResult(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))`);
    const drawerClosedOnEsc = await evalResult(`document.getElementById('mobileDrawer').classList.contains('hidden')`);
    assert(drawerClosedOnEsc, 'Pressing Escape dismisses mobile drawer');

    console.log('\n=== TIER 5: Multi-Viewport Responsive Overflow Sweep (7 Viewports) ===');

    const viewports = [
      { name: '2560x1440 (2K Ultrawide Monitor)', w: 2560, h: 1440 },
      { name: '1920x1080 (Desktop Standard)', w: 1920, h: 1080 },
      { name: '1440x900 (Laptop Standard)', w: 1440, h: 900 },
      { name: '1024x768 (Tablet Landscape)', w: 1024, h: 768 },
      { name: '768x1024 (Tablet Portrait)', w: 768, h: 1024 },
      { name: '390x844 (Mobile Baseline)', w: 390, h: 844 },
      { name: '320x568 (Adversarial Ultra-Narrow)', w: 320, h: 568 }
    ];

    for (const vp of viewports) {
      await send('Emulation.setDeviceMetricsOverride', {
        width: vp.w,
        height: vp.h,
        deviceScaleFactor: 1,
        mobile: vp.w < 768
      });
      await new Promise(r => setTimeout(r, 200));

      const overflow = await evalResult(`
        (() => {
          const docEl = document.documentElement;
          const body = document.body;
          const scrollW = Math.max(docEl.scrollWidth, body.scrollWidth);
          const clientW = docEl.clientWidth;
          return { scrollW, clientW, diff: scrollW - clientW };
        })()
      `);

      const hasNoOverflow = overflow.scrollW <= overflow.clientW + 1;
      if (!hasNoOverflow) {
        const culprits = await evalResult(`
          (() => {
            const list = [];
            document.querySelectorAll('*').forEach(el => {
              const r = el.getBoundingClientRect();
              if (r.right > ${vp.w} + 2) {
                list.push({ tag: el.tagName, id: el.id, cls: (el.className || '').slice(0, 40), right: Math.round(r.right), w: Math.round(r.width) });
              }
            });
            return list.slice(0, 8);
          })()
        `);
        console.log('    Culprits for overflow:', JSON.stringify(culprits));
      }
      assert(hasNoOverflow, `Viewport ${vp.name}: Zero horizontal overflow`, `scroll=${overflow.scrollW}px, client=${overflow.clientW}px`);
    }

    console.log('\n========================================================================');
    console.log(`Immersive Landing Suite Summary:`);
    console.log(`  Passed: ${passed}`);
    console.log(`  Failed: ${failed}`);
    console.log('========================================================================\n');

    ws.close();
  } catch (err) {
    console.error('Test runner exception:', err);
    failed++;
  } finally {
    chrome.kill();
    server.close();
    process.exit(failed > 0 ? 1 : 0);
  }
});

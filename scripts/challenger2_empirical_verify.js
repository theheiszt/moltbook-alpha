#!/usr/bin/env node
/**
 * Challenger 2 Empirical Verification Suite
 * Milestone 1 Iteration 2 Gate Verification
 * Target: I:\Scripts and Programs\moltbook-site\dashboard.html
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const SITE_DIR = path.resolve(__dirname, '..');
const CHROME_PATH = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

function startLocalServer(rootDir) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      let reqPath = decodeURI(req.url.split('?')[0]);
      if (reqPath === '/' || reqPath === '') reqPath = '/dashboard.html';

      const filePath = path.join(rootDir, reqPath);
      if (!filePath.startsWith(rootDir)) {
        res.writeHead(403);
        res.end('Forbidden');
        return;
      }

      fs.stat(filePath, (err, stats) => {
        if (err || !stats.isFile()) {
          res.writeHead(404, { 'Content-Type': 'text/plain' });
          res.end(`404 Not Found: ${reqPath}`);
          return;
        }

        const ext = path.extname(filePath).toLowerCase();
        const contentType = MIME_TYPES[ext] || 'application/octet-stream';

        res.writeHead(200, {
          'Content-Type': contentType,
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'no-cache, no-store, must-revalidate',
        });

        const stream = fs.createReadStream(filePath);
        stream.pipe(res);
      });
    });

    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      resolve({ server, port, url: `http://127.0.0.1:${port}` });
    });

    server.on('error', reject);
  });
}

class ChromeSession {
  constructor(chromePath, cdpPort) {
    this.chromePath = chromePath;
    this.cdpPort = cdpPort;
    this.proc = null;
    this.ws = null;
    this.msgId = 1;
    this.pending = new Map();
  }

  async launch() {
    this.proc = spawn(this.chromePath, [
      '--headless=new',
      '--disable-gpu',
      `--remote-debugging-port=${this.cdpPort}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-background-networking',
      '--disable-sync',
      'about:blank',
    ]);

    let ready = false;
    for (let i = 0; i < 40; i++) {
      await new Promise(r => setTimeout(r, 150));
      try {
        const res = await fetch(`http://127.0.0.1:${this.cdpPort}/json/version`);
        if (res.ok) {
          ready = true;
          break;
        }
      } catch (e) {}
    }

    if (!ready) throw new Error(`Chrome debugging port ${this.cdpPort} unavailable.`);

    const listRes = await fetch(`http://127.0.0.1:${this.cdpPort}/json/list`);
    const targets = await listRes.json();
    let pageTarget = targets.find(t => t.type === 'page');

    if (!pageTarget) {
      const newRes = await fetch(`http://127.0.0.1:${this.cdpPort}/json/new`, { method: 'PUT' });
      pageTarget = await newRes.json();
    }

    const wsUrl = pageTarget.webSocketDebuggerUrl;
    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) reject(new Error(`CDP Error (${msg.error.code}): ${msg.error.message}`));
          else resolve(msg.result);
        }
      } catch (err) {}
    };

    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });

    await this.send('Page.enable');
    await this.send('Runtime.enable');
    await this.send('DOM.enable');
  }

  send(method, params = {}) {
    const id = this.msgId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression, awaitPromise = false) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise,
    });
    if (res.exceptionDetails) {
      const desc = res.exceptionDetails.exception?.description || res.exceptionDetails.text;
      throw new Error(`Browser Eval Exception: ${desc}`);
    }
    return res.result?.value;
  }

  async setViewport(width, height, mobile = false) {
    await this.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile,
    });
    await new Promise(r => setTimeout(r, 200));
  }

  async close() {
    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
    }
    if (this.proc) {
      try { this.proc.kill('SIGKILL'); } catch (e) {}
    }
  }
}

async function runEmpiricalVerification() {
  console.log("========================================================================");
  console.log("  CHALLENGER 2: EMPIRICAL VERIFICATION HARNESS (M1 IT2 GATE)");
  console.log("========================================================================\n");

  const results = [];
  function assert(group, title, passed, details = "") {
    results.push({ group, title, passed, details });
    const mark = passed ? "✓ PASS" : "✗ FAIL";
    console.log(`  ${mark} [${group}] ${title}${details ? " (" + details + ")" : ""}`);
  }

  const server = await startLocalServer(SITE_DIR);
  console.log(`• Local HTTP test server running at ${server.url}`);

  const cdpPort = 9222 + Math.floor(Math.random() * 500);
  console.log(`• Launching Headless Chrome on CDP port ${cdpPort}...`);
  const chrome = new ChromeSession(CHROME_PATH, cdpPort);
  await chrome.launch();

  try {
    const targetUrl = `${server.url}/dashboard.html#sentinel`;
    await chrome.send('Page.navigate', { url: targetUrl });
    await new Promise(r => setTimeout(r, 2000));

    // Ensure Sentinel view is switched on
    await chrome.eval(`(() => {
      if (typeof window.switchView === 'function') {
        window.switchView('sentinel');
      }
    })()`);
    await new Promise(r => setTimeout(r, 400));

    // Global canary tracker
    await chrome.eval(`
      window.__CHALLENGER_XSS_TRIGGERS = [];
      window.__challenger_xss_sink = function(source) {
        window.__CHALLENGER_XSS_TRIGGERS.push(source);
      };
    `);

    const PAYLOAD_CORPUS = [
      '<script>window.__challenger_xss_sink("script_tag")</script>',
      '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" onload="window.__challenger_xss_sink(\'img_onload\')">',
      '<img src="invalid_url_sink" onerror="window.__challenger_xss_sink(\'img_onerror\')">',
      '<svg onload="window.__challenger_xss_sink(\'svg_onload\')">',
      '<svg><script>window.__challenger_xss_sink("svg_script")</script></svg>',
      '"><script>window.__challenger_xss_sink("attr_breakout_script")</script>',
      '"><img src=x onerror="window.__challenger_xss_sink(\'attr_breakout_img\')">',
      '\' onfocus="window.__challenger_xss_sink(\'onfocus\')" autofocus=\'',
      'javascript:window.__challenger_xss_sink("js_uri")',
      '<iframe src="javascript:window.__challenger_xss_sink(\'iframe\')"></iframe>',
      '<details open ontoggle="window.__challenger_xss_sink(\'details_ontoggle\')">',
      '<body onload="window.__challenger_xss_sink(\'body_onload\')">'
    ];

    // =========================================================================
    // SECTION 1: XSS EMPIRICAL AUDIT ON 4 SPECIFIED FUNCTIONS
    // =========================================================================
    console.log("\n--- SECTION 1: EMPIRICAL XSS HARDENING ON 4 SPECIFIED FUNCTIONS ---");

    // 1. renderIncidentTimeline
    const timelineResult = await chrome.eval(`
      (() => {
        const testContainer = document.createElement("div");
        document.body.appendChild(testContainer);

        const payloads = ${JSON.stringify(PAYLOAD_CORPUS)};
        let elementsInjected = 0;
        let testCount = 0;

        for (const p of payloads) {
          testCount++;
          const incident = {
            severity: p,
            title: p,
            description: p,
            time: p
          };
          const html = window.renderIncidentTimeline([incident]);
          testContainer.innerHTML = html;

          if (testContainer.querySelector("script") ||
              testContainer.querySelector("img") ||
              testContainer.querySelector("svg") ||
              testContainer.querySelector("iframe") ||
              testContainer.querySelector("details")) {
            elementsInjected++;
          }
        }
        testContainer.remove();

        return { testCount, elementsInjected };
      })()
    `);
    await new Promise(r => setTimeout(r, 200));
    const triggersAfterTimeline = await chrome.eval(`window.__CHALLENGER_XSS_TRIGGERS.length`);

    assert(
      "XSS Audit",
      "renderIncidentTimeline: zero unescaped tags entered DOM & zero sinks fired",
      timelineResult.elementsInjected === 0 && triggersAfterTimeline === 0,
      `Tested ${timelineResult.testCount} payloads, injected tags: ${timelineResult.elementsInjected}, triggers: ${triggersAfterTimeline}`
    );

    // 2. renderCryptoStatusCard
    const cryptoResult = await chrome.eval(`
      (() => {
        const testContainer = document.createElement("div");
        document.body.appendChild(testContainer);

        const payloads = ${JSON.stringify(PAYLOAD_CORPUS)};
        let elementsInjected = 0;
        let testCount = 0;

        for (const p of payloads) {
          testCount++;
          const witness = {
            key_id: p,
            witness_id: p,
            fingerprint: p,
            verified: true
          };
          const html = window.renderCryptoStatusCard(witness);
          testContainer.innerHTML = html;

          if (testContainer.querySelector("script") ||
              testContainer.querySelector("img") ||
              testContainer.querySelector("svg") ||
              testContainer.querySelector("iframe") ||
              testContainer.querySelector("details")) {
            elementsInjected++;
          }
        }
        testContainer.remove();

        return { testCount, elementsInjected };
      })()
    `);
    await new Promise(r => setTimeout(r, 200));
    const triggersAfterCrypto = await chrome.eval(`window.__CHALLENGER_XSS_TRIGGERS.length`);

    assert(
      "XSS Audit",
      "renderCryptoStatusCard: zero unescaped tags entered DOM & zero sinks fired",
      cryptoResult.elementsInjected === 0 && triggersAfterCrypto === 0,
      `Tested ${cryptoResult.testCount} payloads, injected tags: ${cryptoResult.elementsInjected}, triggers: ${triggersAfterCrypto}`
    );

    // 3. renderRiskGauge
    const gaugeResult = await chrome.eval(`
      (() => {
        const testContainer = document.createElement("div");
        document.body.appendChild(testContainer);

        const payloads = ${JSON.stringify(PAYLOAD_CORPUS)};
        let elementsInjected = 0;
        let testCount = 0;

        for (const p of payloads) {
          testCount++;
          const html = window.renderRiskGauge(50, p);
          testContainer.innerHTML = html;

          // Note: renderRiskGauge natively contains its own circular SVG,
          // so we check if any malicious svg script/img/iframe/details or external img/script was injected
          const script = testContainer.querySelector("script");
          const img = testContainer.querySelector("img");
          const iframe = testContainer.querySelector("iframe");
          const details = testContainer.querySelector("details");
          const svgScripts = testContainer.querySelectorAll("svg script");

          if (script || img || iframe || details || svgScripts.length > 0) {
            elementsInjected++;
          }
        }
        testContainer.remove();

        return { testCount, elementsInjected };
      })()
    `);
    await new Promise(r => setTimeout(r, 200));
    const triggersAfterGauge = await chrome.eval(`window.__CHALLENGER_XSS_TRIGGERS.length`);

    assert(
      "XSS Audit",
      "renderRiskGauge: zero unescaped classification tags entered DOM & zero sinks fired",
      gaugeResult.elementsInjected === 0 && triggersAfterGauge === 0,
      `Tested ${gaugeResult.testCount} payloads, injected tags: ${gaugeResult.elementsInjected}, triggers: ${triggersAfterGauge}`
    );

    // 4. renderLiveAnomalies
    const anomalyResult = await chrome.eval(`
      (() => {
        const payloads = ${JSON.stringify(PAYLOAD_CORPUS)};
        let elementsInjected = 0;
        let testCount = 0;

        const liveContainer = document.getElementById("liveAnomaliesContainer");
        const originalHtml = liveContainer ? liveContainer.innerHTML : "";

        for (const p of payloads) {
          testCount++;
          const anomalies = [
            {
              pool_address: p,
              chain: p,
              overall_risk_score: 90,
              headline: p,
              assessed_at: '2026-11-04T05:00:00Z'
            }
          ];
          window.renderLiveAnomalies(anomalies);

          if (liveContainer) {
            if (liveContainer.querySelector("script") ||
                liveContainer.querySelector("img") ||
                liveContainer.querySelector("svg") ||
                liveContainer.querySelector("iframe") ||
                liveContainer.querySelector("details")) {
              elementsInjected++;
            }
          }
        }

        if (liveContainer) liveContainer.innerHTML = originalHtml;

        return { testCount, elementsInjected };
      })()
    `);
    await new Promise(r => setTimeout(r, 200));
    const triggersAfterAnomaly = await chrome.eval(`window.__CHALLENGER_XSS_TRIGGERS.length`);

    assert(
      "XSS Audit",
      "renderLiveAnomalies: zero unescaped pool/chain/headline tags entered DOM & zero sinks fired",
      anomalyResult.elementsInjected === 0 && triggersAfterAnomaly === 0,
      `Tested ${anomalyResult.testCount} payloads, injected tags: ${anomalyResult.elementsInjected}, triggers: ${triggersAfterAnomaly}`
    );

    // =========================================================================
    // SECTION 2: SUB-390PX VIEWPORT RESPONSIVE LAYOUT AUDIT
    // =========================================================================
    console.log("\n--- SECTION 2: SUB-390PX RESPONSIVE OVERFLOW SWEEP ---");

    const SUB_390_VIEWPORTS = [
      { name: '390x844 (Mobile Baseline)', width: 390, height: 844 },
      { name: '375x667 (iPhone SE Compact)', width: 375, height: 667 },
      { name: '360x800 (Samsung Galaxy Android)', width: 360, height: 800 },
      { name: '340x600 (Narrow Feature Phone)', width: 340, height: 600 },
      { name: '320x568 (Adversarial Ultra-Narrow 320px)', width: 320, height: 568 },
    ];

    for (const vp of SUB_390_VIEWPORTS) {
      await chrome.setViewport(vp.width, vp.height, true);

      const metrics = await chrome.eval(`
        (() => {
          const doc = document.documentElement;
          const body = document.body;
          const scrollWidth = Math.max(doc.scrollWidth, body.scrollWidth);
          const clientWidth = doc.clientWidth;
          const overflowDelta = scrollWidth - clientWidth;
          const hasOverflow = overflowDelta > 0.5;

          const overflowingEls = [];
          if (hasOverflow) {
            document.querySelectorAll('*').forEach(el => {
              const r = el.getBoundingClientRect();
              if (r.right > clientWidth + 0.5) {
                overflowingEls.push({
                  tag: el.tagName,
                  id: el.id,
                  cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 50) : '',
                  right: Math.round(r.right),
                  width: Math.round(r.width)
                });
              }
            });
          }

          return {
            scrollWidth,
            clientWidth,
            overflowDelta,
            hasOverflow,
            overflowingEls: overflowingEls.slice(0, 5)
          };
        })()
      `);

      const details = metrics.hasOverflow
        ? `Overflow detected: scrollWidth=${metrics.scrollWidth}px > clientWidth=${metrics.clientWidth}px (+${metrics.overflowDelta}px) Elements: ${JSON.stringify(metrics.overflowingEls)}`
        : `scrollWidth=${metrics.scrollWidth}px, clientWidth=${metrics.clientWidth}px`;

      assert(
        "Viewport Audit",
        `Viewport ${vp.name}: Zero horizontal overflow (scrollWidth <= clientWidth)`,
        !metrics.hasOverflow,
        details
      );
    }

    // =========================================================================
    // SECTION 3: SPECIFIC REMEDIATION TARGET CHECKS
    // =========================================================================
    console.log("\n--- SECTION 3: SPECIFIC REMEDIATED COMPONENT INTEGRITY CHECKS ---");

    const remediationChecks = await chrome.eval(`
      (() => {
        // Check 1: #agentDossierCard header has flex-wrap and min-w-0
        const dossierCard = document.getElementById("agentDossierCard");
        let dossierHasWrap = false;
        if (dossierCard) {
          const flexWrapEl = dossierCard.querySelector(".flex-wrap");
          if (flexWrapEl && flexWrapEl.className.includes("items-center")) {
            dossierHasWrap = true;
          }
        }

        // Check 2: #currentDigestDisplay has break-all
        const digest = document.getElementById("currentDigestDisplay");
        let digestHasBreak = false;
        if (digest && digest.className.includes("break-all")) {
          digestHasBreak = true;
        }

        // Check 3: Check table responsive scroll containers
        const poolTable = document.getElementById("monitoredPoolsTable");
        const tableHasScrollContainer = poolTable ? !!poolTable.closest(".overflow-x-auto") : false;

        return {
          dossierHasWrap,
          digestHasBreak,
          tableHasScrollContainer
        };
      })()
    `);

    assert(
      "Remediation Verification",
      "Agent dossier card header includes flex-wrap for sub-390px adaptation",
      remediationChecks.dossierHasWrap
    );

    assert(
      "Remediation Verification",
      "Current digest display includes break-all for unbroken 64-char hex strings",
      remediationChecks.digestHasBreak
    );

    assert(
      "Remediation Verification",
      "Monitored pools table is housed within an overflow-x-auto container",
      remediationChecks.tableHasScrollContainer
    );

    // =========================================================================
    // Summary
    // =========================================================================
    console.log("\n========================================================================");
    console.log("  CHALLENGER 2 EMPIRICAL VERIFICATION SUMMARY");
    console.log("========================================================================");

    const total = results.length;
    const passed = results.filter(r => r.passed).length;
    const failed = results.filter(r => !r.passed).length;

    console.log(`  Total Checks : ${total}`);
    console.log(`  Passed       : ${passed}`);
    console.log(`  Failed       : ${failed}`);
    console.log(`  VERDICT      : ${failed === 0 ? "APPROVE" : "REQUEST_CHANGES"}`);
    console.log("========================================================================\n");

    return { total, passed, failed, results };

  } finally {
    await chrome.close();
    server.server.close();
  }
}

runEmpiricalVerification().then(({ failed }) => {
  process.exit(failed > 0 ? 1 : 0);
}).catch(err => {
  console.error("Fatal verification error:", err);
  process.exit(1);
});

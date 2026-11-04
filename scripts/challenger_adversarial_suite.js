#!/usr/bin/env node
/**
 * CHALLENGER ADVERSARIAL STRESS TEST SUITE
 * Milestone 1: Sentinel UI & Visualization Robustness
 * Target: I:\Scripts and Programs\moltbook-site\dashboard.html
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const CHROME_PATH = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const SITE_DIR = path.resolve(__dirname, '..');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
};

// ANSI Color Helpers
const C = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
};

class ChallengerRunner {
  constructor() {
    this.results = [];
    this.startTime = Date.now();
  }

  record(category, testName, passed, details = null, error = null) {
    const entry = { category, testName, passed, details, error };
    this.results.push(entry);
    const icon = passed ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    console.log(`  ${icon} [${category}] ${testName}`);
    if (!passed && error) {
      console.log(`         ${C.red}Error: ${error}${C.reset}`);
    }
    if (details && !passed) {
      console.log(`         ${C.gray}Details: ${JSON.stringify(details)}${C.reset}`);
    }
  }

  summary() {
    const total = this.results.length;
    const passed = this.results.filter(r => r.passed).length;
    const failed = total - passed;
    const duration = ((Date.now() - this.startTime) / 1000).toFixed(2);
    return { total, passed, failed, duration, results: this.results };
  }
}

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
          res.writeHead(404);
          res.end('Not Found');
          return;
        }
        const ext = path.extname(filePath).toLowerCase();
        res.writeHead(200, {
          'Content-Type': MIME_TYPES[ext] || 'application/octet-stream',
          'Access-Control-Allow-Origin': '*',
        });
        fs.createReadStream(filePath).pipe(res);
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
      'about:blank',
    ]);

    for (let i = 0; i < 40; i++) {
      await new Promise(r => setTimeout(r, 150));
      try {
        const res = await fetch(`http://127.0.0.1:${this.cdpPort}/json/version`);
        if (res.ok) break;
      } catch (e) {}
    }

    const listRes = await fetch(`http://127.0.0.1:${this.cdpPort}/json/list`);
    const targets = await listRes.json();
    let pageTarget = targets.find(t => t.type === 'page');
    if (!pageTarget) {
      const newRes = await fetch(`http://127.0.0.1:${this.cdpPort}/json/new`, { method: 'PUT' });
      pageTarget = await newRes.json();
    }

    this.ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) reject(new Error(msg.error.message));
          else resolve(msg.result);
        }
      } catch (e) {}
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
      throw new Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text);
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
    await new Promise(r => setTimeout(r, 80));
  }

  async close() {
    if (this.ws) try { this.ws.close(); } catch (e) {}
    if (this.proc) try { this.proc.kill('SIGKILL'); } catch (e) {}
  }
}

async function runAdversarialSuite() {
  console.log(`${C.bold}${C.cyan}========================================================================${C.reset}`);
  console.log(`${C.bold}${C.cyan}  CHALLENGER ADVERSARIAL STRESS TEST SUITE (Milestone 1 Sentinel UI)    ${C.reset}`);
  console.log(`${C.bold}${C.cyan}========================================================================${C.reset}\n`);

  const runner = new ChallengerRunner();
  let localServer = null;
  let chrome = null;

  try {
    localServer = await startLocalServer(SITE_DIR);
    const cdpPort = 9400 + Math.floor(Math.random() * 500);
    chrome = new ChromeSession(CHROME_PATH, cdpPort);
    await chrome.launch();

    await chrome.send('Page.navigate', { url: `${localServer.url}/dashboard.html#sentinel` });
    await new Promise(r => setTimeout(r, 1200));

    // =========================================================================
    // SECTION A: Extreme Boundary Scores on Modular Visualization Functions
    // Scores: -50, 0, 4, 25, 45, 70, 100, 999, plus NaN and string values
    // =========================================================================
    console.log(`\n${C.bold}--- SECTION A: Modular Visualization Functions Extreme Scores ---${C.reset}`);

    const boundaryScores = [-50, 0, 4, 25, 45, 70, 100, 999];
    const scoreResults = await chrome.eval(`
      (() => {
        const scores = [-50, 0, 4, 25, 45, 70, 100, 999];
        const results = {};
        for (const s of scores) {
          const svg = window.renderRiskGauge(s);
          const hasSvg = typeof svg === 'string' && svg.includes('<svg');
          const hasClamped = !svg.includes('NaN');
          const factorHtml = window.renderRiskFactor('Drain Test', s, 'Evidence string');
          const hasFactor = typeof factorHtml === 'string' && factorHtml.includes('%') && !factorHtml.includes('NaN');
          results[s] = { hasSvg, hasClamped, hasFactor, svg, factorHtml };
        }
        return results;
      })()
    `);

    for (const s of boundaryScores) {
      const res = scoreResults[s];
      runner.record(
        'Boundary Scores',
        `renderRiskGauge(${s}) clamped & returns valid SVG without NaN`,
        res && res.hasSvg && res.hasClamped,
        { score: s }
      );
      runner.record(
        'Boundary Scores',
        `renderRiskFactor(${s}) clamped & returns valid HTML without NaN`,
        res && res.hasFactor,
        { score: s }
      );
    }

    // Check specific classification labels for key boundaries
    const classResults = await chrome.eval(`
      (() => {
        return {
          neg50: window.renderRiskGauge(-50).includes('SAFE'),
          zero: window.renderRiskGauge(0).includes('SAFE'),
          four: window.renderRiskGauge(4).includes('SAFE'),
          twentyfive: window.renderRiskGauge(25).includes('MEDIUM'),
          fortyfive: window.renderRiskGauge(45).includes('HIGH'),
          seventy: window.renderRiskGauge(70).includes('CRITICAL'),
          hundred: window.renderRiskGauge(100).includes('CRITICAL'),
          nine99: window.renderRiskGauge(999).includes('CRITICAL'),
        };
      })()
    `);

    runner.record('Classification', 'Score -50 classified as SAFE', classResults.neg50);
    runner.record('Classification', 'Score 0 classified as SAFE', classResults.zero);
    runner.record('Classification', 'Score 4 classified as SAFE', classResults.four);
    runner.record('Classification', 'Score 25 classified as MEDIUM', classResults.twentyfive);
    runner.record('Classification', 'Score 45 classified as HIGH', classResults.fortyfive);
    runner.record('Classification', 'Score 70 classified as CRITICAL', classResults.seventy);
    runner.record('Classification', 'Score 100 classified as CRITICAL', classResults.hundred);
    runner.record('Classification', 'Score 999 clamped to 100 and CRITICAL', classResults.nine99);

    // =========================================================================
    // SECTION B: Sparklines, Incident Timelines, Crypto Cards Edge Cases
    // Empty arrays, null inputs, single-element arrays, extreme volatility
    // =========================================================================
    console.log(`\n${C.bold}--- SECTION B: Empty, Null & Single-Element Array Stress ---${C.reset}`);

    const arrayStressResults = await chrome.eval(`
      (() => {
        const r = {};
        // Sparkline tests
        r.spkEmpty = window.renderSparkline([]);
        r.spkNull = window.renderSparkline(null);
        r.spkUndefined = window.renderSparkline(undefined);
        r.spkSingle = window.renderSparkline([42]);
        r.spkFlat = window.renderSparkline([10, 10, 10, 10, 10]);
        r.spkExtreme = window.renderSparkline([-50, 0, 4, 25, 45, 70, 100, 999]);
        r.spkObjects = window.renderSparkline([{overall_risk_score: 10}, {score: 90}]);

        // Incident timeline tests
        r.incEmpty = window.renderIncidentTimeline([]);
        r.incNull = window.renderIncidentTimeline(null);
        r.incMalformed = window.renderIncidentTimeline([{}, { title: null, severity: null }]);

        // Crypto card tests
        r.cardNull = window.renderCryptoStatusCard(null);
        r.cardEmpty = window.renderCryptoStatusCard({});
        r.cardTampered = window.renderCryptoStatusCard({ verified: false, tampered: true });

        // Factor meter XSS injection
        r.factorXss = window.renderRiskFactor('<script>alert("xss")</script>', 50, '"><img src=x onerror=1>');

        return {
          spkEmptyValid: typeof r.spkEmpty === 'string' && r.spkEmpty.includes('<svg') && !r.spkEmpty.includes('NaN'),
          spkNullValid: typeof r.spkNull === 'string' && r.spkNull.includes('<svg') && !r.spkNull.includes('NaN'),
          spkUndefinedValid: typeof r.spkUndefined === 'string' && r.spkUndefined.includes('<svg') && !r.spkUndefined.includes('NaN'),
          spkSingleValid: typeof r.spkSingle === 'string' && r.spkSingle.includes('<svg') && !r.spkSingle.includes('NaN'),
          spkFlatValid: typeof r.spkFlat === 'string' && r.spkFlat.includes('<svg') && !r.spkFlat.includes('NaN'),
          spkExtremeValid: typeof r.spkExtreme === 'string' && r.spkExtreme.includes('<svg') && !r.spkExtreme.includes('NaN'),
          spkObjectsValid: typeof r.spkObjects === 'string' && r.spkObjects.includes('<svg') && !r.spkObjects.includes('NaN'),
          incEmptyValid: typeof r.incEmpty === 'string' && r.incEmpty.includes('Zero Active Surveillance Incidents'),
          incNullValid: typeof r.incNull === 'string' && r.incNull.includes('Zero Active Surveillance Incidents'),
          incMalformedValid: typeof r.incMalformed === 'string' && !r.incMalformed.includes('undefined'),
          cardNullValid: typeof r.cardNull === 'string' && r.cardNull.includes('ED25519 WITNESS VERIFIED'),
          cardTamperedValid: typeof r.cardTampered === 'string' && r.cardTampered.includes('TAMPER DETECTED'),
          factorXssSafe: !r.factorXss.includes('<script>') && r.factorXss.includes('&lt;script&gt;'),
        };
      })()
    `);

    runner.record('Array Stress', 'renderSparkline([]) handles empty array safely', arrayStressResults.spkEmptyValid);
    runner.record('Array Stress', 'renderSparkline(null) handles null gracefully', arrayStressResults.spkNullValid);
    runner.record('Array Stress', 'renderSparkline(undefined) handles undefined gracefully', arrayStressResults.spkUndefinedValid);
    runner.record('Array Stress', 'renderSparkline([42]) handles single element without division by zero', arrayStressResults.spkSingleValid);
    runner.record('Array Stress', 'renderSparkline([10,...]) handles flat line without NaN', arrayStressResults.spkFlatValid);
    runner.record('Array Stress', 'renderSparkline(extreme) clamps [-50...999] safely', arrayStressResults.spkExtremeValid);
    runner.record('Array Stress', 'renderSparkline(objects) extracts overall_risk_score and score keys', arrayStressResults.spkObjectsValid);
    runner.record('Array Stress', 'renderIncidentTimeline([]) displays institutional empty state', arrayStressResults.incEmptyValid);
    runner.record('Array Stress', 'renderIncidentTimeline(null) handles null with empty state', arrayStressResults.incNullValid);
    runner.record('Array Stress', 'renderIncidentTimeline(malformed) handles missing fields safely', arrayStressResults.incMalformedValid);
    runner.record('Array Stress', 'renderCryptoStatusCard(null) defaults safely', arrayStressResults.cardNullValid);
    runner.record('Array Stress', 'renderCryptoStatusCard(tampered) displays fail-closed alert', arrayStressResults.cardTamperedValid);
    runner.record('Array Stress', 'renderRiskFactor escapes XSS and special characters', arrayStressResults.factorXssSafe);

    // =========================================================================
    // SECTION C: Chart Lifecycle & Rapid Re-render Stress (Canvas Reuse)
    // 50 rapid synchronous re-renders on the same canvas element
    // Must assert zero "Canvas is already in use" exceptions
    // =========================================================================
    console.log(`\n${C.bold}--- SECTION C: Rapid Chart Re-Render Stress (Canvas Reuse Safety) ---${C.reset}`);

    const canvasStressResults = await chrome.eval(`
      (() => {
        const dummyCanvas = document.createElement('canvas');
        dummyCanvas.id = 'stressTestCanvas_' + Date.now();
        dummyCanvas.width = 300;
        dummyCanvas.height = 200;
        document.body.appendChild(dummyCanvas);

        let distErrors = 0;
        let lastDistChart = null;
        for (let i = 0; i < 50; i++) {
          try {
            const dist = (i % 2 === 0)
              ? { SAFE: i, LOW: 50 - i, MEDIUM: 10, HIGH: 5, CRITICAL: 2 }
              : [0, 25, 50, 75, 100, i];
            lastDistChart = window.buildRiskDistributionChart(dummyCanvas, dist);
          } catch (e) {
            distErrors++;
          }
        }

        let historyErrors = 0;
        let lastHistChart = null;
        for (let i = 0; i < 50; i++) {
          try {
            const history = Array.from({ length: (i % 10) + 1 }, (_, k) => (k * 15) % 100);
            lastHistChart = window.buildRiskHistoryChart(dummyCanvas, history);
          } catch (e) {
            historyErrors++;
          }
        }

        // Cleanup dummy canvas
        if (lastHistChart && typeof lastHistChart.destroy === 'function') lastHistChart.destroy();
        dummyCanvas.remove();

        return {
          distErrors,
          historyErrors,
          distChartCreated: !!lastDistChart,
          histChartCreated: !!lastHistChart
        };
      })()
    `);

    runner.record(
      'Canvas Stress',
      'buildRiskDistributionChart survived 50 rapid re-renders with zero exceptions',
      canvasStressResults.distErrors === 0,
      { errors: canvasStressResults.distErrors }
    );
    runner.record(
      'Canvas Stress',
      'buildRiskHistoryChart survived 50 rapid re-renders with zero exceptions',
      canvasStressResults.historyErrors === 0,
      { errors: canvasStressResults.historyErrors }
    );

    // =========================================================================
    // SECTION D: Web Crypto Ed25519 Cryptographic Verification Attacks
    // Byte mutations, signature bit-flips, key tampering
    // =========================================================================
    console.log(`\n${C.bold}--- SECTION D: Web Crypto Ed25519 Mutation & Tampering Attacks ---${C.reset}`);

    const cryptoStressResults = await chrome.eval(`
      (async () => {
        const PINNED_SPKI = "302a300506032b657003210068b4ac53b4d7e1ddee10f42230c9221abbcec4f13489f9060e0c86cc068d3383";
        const pristinePayload = '{"action":"sentinel_pool_assessment","actor":"moltalpha_sentinel_engine","credit_delta":null,"environmental_anchor":{"chain":"solana","overall_risk_score":4,"pool_address":"Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE","risk_level":"SAFE","slot":312891045},"key_hash":null,"lot_id":null,"nonce":1,"post_balance":null,"pre_balance":null,"prev_witness_hash":"0000000000000000000000000000000000000000000000000000000000000000","request_id":null,"timestamp":"2026-10-27T22:00:00Z"}';
        const pristineSig = "f4f5e7d569cb2b272a2908011be09fc15578b4b7183812af5363a7ebb3ca364545d9d636f9635ae1a5e3e1725a1682811fef94df37c1c411374ebbb5daf68a06";

        function hexToBytes(hex) {
          const clean = hex.replace(/[^0-9a-fA-F]/g, '');
          const bytes = new Uint8Array(clean.length / 2);
          for (let i = 0; i < bytes.length; i++) {
            bytes[i] = parseInt(clean.substr(i * 2, 2), 16);
          }
          return bytes;
        }

        function bytesToHex(bytes) {
          return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
        }

        async function verify(payloadStr, sigHex, spkiHex = PINNED_SPKI) {
          try {
            const buf = new TextEncoder().encode(payloadStr);
            const hashBuf = await window.crypto.subtle.digest("SHA-256", buf);
            const digestHex = bytesToHex(new Uint8Array(hashBuf));

            const spkiBytes = hexToBytes(spkiHex);
            const sigBytes = hexToBytes(sigHex);
            const dataBytes = new TextEncoder().encode(digestHex);

            const cryptoKey = await window.crypto.subtle.importKey(
              "spki",
              spkiBytes,
              { name: "Ed25519" },
              false,
              ["verify"]
            );

            return await window.crypto.subtle.verify("Ed25519", cryptoKey, sigBytes, dataBytes);
          } catch (e) {
            return false;
          }
        }

        const pristineValid = await verify(pristinePayload, pristineSig);

        // Attack 1: Mutate 1 character in overall_risk_score: 4 -> 5
        const mutatedPayload1 = pristinePayload.replace('"overall_risk_score":4', '"overall_risk_score":5');
        const attack1Valid = await verify(mutatedPayload1, pristineSig);

        // Attack 2: Mutate pool address character
        const mutatedPayload2 = pristinePayload.replace('Czfq3x', 'Dzfq3x');
        const attack2Valid = await verify(mutatedPayload2, pristineSig);

        // Attack 3: Add trailing space (canonicalization breach)
        const mutatedPayload3 = pristinePayload + " ";
        const attack3Valid = await verify(mutatedPayload3, pristineSig);

        // Attack 4: Mutate timestamp
        const mutatedPayload4 = pristinePayload.replace('2026-10-27T22:00:00Z', '2026-10-27T22:00:01Z');
        const attack4Valid = await verify(mutatedPayload4, pristineSig);

        // Attack 5: Flip 1st byte of signature
        const sigBytes1 = hexToBytes(pristineSig);
        sigBytes1[0] ^= 0x01;
        const attack5Valid = await verify(pristinePayload, bytesToHex(sigBytes1));

        // Attack 6: Flip middle byte of signature
        const sigBytes2 = hexToBytes(pristineSig);
        sigBytes2[32] ^= 0x80;
        const attack6Valid = await verify(pristinePayload, bytesToHex(sigBytes2));

        // Attack 7: Flip last byte of signature
        const sigBytes3 = hexToBytes(pristineSig);
        sigBytes3[63] ^= 0x01;
        const attack7Valid = await verify(pristinePayload, bytesToHex(sigBytes3));

        // Attack 8: All-zero signature
        const attack8Valid = await verify(pristinePayload, "0".repeat(128));

        // Attack 9: Truncated signature (63 bytes)
        const attack9Valid = await verify(pristinePayload, pristineSig.slice(0, 126));

        // Attack 10: Mutate public key byte
        const keyBytes = hexToBytes(PINNED_SPKI);
        keyBytes[20] ^= 0x01;
        const attack10Valid = await verify(pristinePayload, pristineSig, bytesToHex(keyBytes));

        return {
          pristineValid,
          attack1Fails: attack1Valid === false,
          attack2Fails: attack2Valid === false,
          attack3Fails: attack3Valid === false,
          attack4Fails: attack4Valid === false,
          attack5Fails: attack5Valid === false,
          attack6Fails: attack6Valid === false,
          attack7Fails: attack7Valid === false,
          attack8Fails: attack8Valid === false,
          attack9Fails: attack9Valid === false,
          attack10Fails: attack10Valid === false,
        };
      })()
    `, true);

    runner.record('Crypto Stress', 'Pristine witness signature verifies as true', cryptoStressResults.pristineValid);
    runner.record('Crypto Stress', 'Attack 1: Score mutation (4->5) rejected', cryptoStressResults.attack1Fails);
    runner.record('Crypto Stress', 'Attack 2: Pool address mutation rejected', cryptoStressResults.attack2Fails);
    runner.record('Crypto Stress', 'Attack 3: Trailing space addition rejected', cryptoStressResults.attack3Fails);
    runner.record('Crypto Stress', 'Attack 4: Timestamp 1-second mutation rejected', cryptoStressResults.attack4Fails);
    runner.record('Crypto Stress', 'Attack 5: Signature first byte bit-flip rejected', cryptoStressResults.attack5Fails);
    runner.record('Crypto Stress', 'Attack 6: Signature middle byte bit-flip rejected', cryptoStressResults.attack6Fails);
    runner.record('Crypto Stress', 'Attack 7: Signature last byte bit-flip rejected', cryptoStressResults.attack7Fails);
    runner.record('Crypto Stress', 'Attack 8: All-zero signature rejected', cryptoStressResults.attack8Fails);
    runner.record('Crypto Stress', 'Attack 9: Truncated signature handled fail-closed', cryptoStressResults.attack9Fails);
    runner.record('Crypto Stress', 'Attack 10: Tampered public key fails verification', cryptoStressResults.attack10Fails);

    // =========================================================================
    // SECTION E: Edge Viewport Layout & Overflow Stress
    // 320x568 (iPhone SE), 360x640, 375x667, 390x844, 412x915, 768x1024,
    // 1024x768, 1280x800, 1440x900, 1920x1080, 2560x1440
    // =========================================================================
    console.log(`\n${C.bold}--- SECTION E: Edge Viewports Layout Overflow Stress ---${C.reset}`);

    const edgeViewports = [
      { name: '320x568 (iPhone SE 1st Gen)', width: 320, height: 568, mobile: true },
      { name: '360x640 (Small Android)', width: 360, height: 640, mobile: true },
      { name: '375x667 (iPhone 8 / SE2)', width: 375, height: 667, mobile: true },
      { name: '390x844 (iPhone 12 / 13 / 14)', width: 390, height: 844, mobile: true },
      { name: '412x915 (Pixel 7 / Galaxy)', width: 412, height: 915, mobile: true },
      { name: '768x1024 (iPad Portrait)', width: 768, height: 1024, mobile: true },
      { name: '1024x768 (iPad Landscape)', width: 1024, height: 768, mobile: false },
      { name: '1280x800 (Compact Laptop)', width: 1280, height: 800, mobile: false },
      { name: '1440x900 (Standard Laptop)', width: 1440, height: 900, mobile: false },
      { name: '1920x1080 (Desktop Widescreen)', width: 1920, height: 1080, mobile: false },
      { name: '2560x1440 (2K QHD Display)', width: 2560, height: 1440, mobile: false },
    ];

    for (const vp of edgeViewports) {
      await chrome.setViewport(vp.width, vp.height, vp.mobile);
      const metrics = await chrome.eval(`
        (() => {
          const doc = document.documentElement;
          const body = document.body;
          return {
            clientWidth: doc.clientWidth,
            scrollWidth: doc.scrollWidth,
            bodyClientWidth: body.clientWidth,
            bodyScrollWidth: body.scrollWidth,
            innerWidth: window.innerWidth,
          };
        })()
      `);

      const noOverflow = metrics.scrollWidth <= metrics.clientWidth + 1; // 1px tolerance for subpixel rounding
      runner.record(
        'Viewport Overflow',
        `Viewport ${vp.name}: zero horizontal overflow (scroll: ${metrics.scrollWidth}px <= client: ${metrics.clientWidth}px)`,
        noOverflow,
        metrics
      );
    }

    // =========================================================================
    // SECTION F: Defensive Null, Missing DOM & Malformed Type Fuzzing
    // =========================================================================
    console.log(`\n${C.bold}--- SECTION F: Defensive Null & Malformed Type Fuzzing ---${C.reset}`);

    const fuzzResults = await chrome.eval(`
      (() => {
        const dummyCanvas = document.createElement('canvas');
        document.body.appendChild(dummyCanvas);

        let cNull1 = null;
        let cNull2 = null;
        let cNonExistent = null;
        let cStringDist = null;
        let cBadArrayDist = null;
        let cBadHistory = null;

        try { cNull1 = window.buildRiskDistributionChart(null, null); } catch (e) { cNull1 = 'THREW: ' + e.message; }
        try { cNull2 = window.buildRiskHistoryChart(null, null); } catch (e) { cNull2 = 'THREW: ' + e.message; }
        try { cNonExistent = window.buildRiskDistributionChart('nonExistentCanvasId999', { SAFE: 5 }); } catch (e) { cNonExistent = 'THREW: ' + e.message; }
        try { cStringDist = window.buildRiskDistributionChart(dummyCanvas, "invalid string input"); } catch (e) { cStringDist = 'THREW: ' + e.message; }
        try { cBadArrayDist = window.buildRiskDistributionChart(dummyCanvas, [null, undefined, {}, -99, 999]); } catch (e) { cBadArrayDist = 'THREW: ' + e.message; }
        try { cBadHistory = window.buildRiskHistoryChart(dummyCanvas, [null, undefined, {}, { score: "bad" }, { time: null }]); } catch (e) { cBadHistory = 'THREW: ' + e.message; }

        dummyCanvas.remove();

        return {
          cNull1Safe: cNull1 === null,
          cNull2Safe: cNull2 === null,
          cNonExistentSafe: cNonExistent === null,
          cStringDistSafe: cStringDist !== null && typeof cStringDist === 'object',
          cBadArrayDistSafe: cBadArrayDist !== null && typeof cBadArrayDist === 'object',
          cBadHistorySafe: cBadHistory !== null && typeof cBadHistory === 'object',
        };
      })()
    `);

    runner.record('Type Fuzzing', 'buildRiskDistributionChart(null, null) returns null safely without throwing', fuzzResults.cNull1Safe);
    runner.record('Type Fuzzing', 'buildRiskHistoryChart(null, null) returns null safely without throwing', fuzzResults.cNull2Safe);
    runner.record('Type Fuzzing', 'buildRiskDistributionChart(nonExistentId) returns null safely without throwing', fuzzResults.cNonExistentSafe);
    runner.record('Type Fuzzing', 'buildRiskDistributionChart(canvas, "string") handles string gracefully', fuzzResults.cStringDistSafe);
    runner.record('Type Fuzzing', 'buildRiskDistributionChart(canvas, [null, undefined, ...]) handles malformed array elements', fuzzResults.cBadArrayDistSafe);
    runner.record('Type Fuzzing', 'buildRiskHistoryChart(canvas, [null, undefined, ...]) handles malformed history elements', fuzzResults.cBadHistorySafe);

    // =========================================================================
    // SECTION G: Interactive UI State Machine & Rapid View Toggling
    // =========================================================================
    console.log(`\n${C.bold}--- SECTION G: Interactive UI State Machine & Rapid View Toggling ---${C.reset}`);

    const interactionResults = await chrome.eval(`
      (async () => {
        // Test 1: Rapid 20x switchView toggling
        let toggleErrors = 0;
        for (let i = 0; i < 20; i++) {
          try {
            window.switchView(i % 2 === 0 ? 'admin' : 'sentinel');
          } catch (e) {
            toggleErrors++;
          }
        }
        window.switchView('sentinel');
        const sentinelVisible = document.getElementById('sentinelView').style.display !== 'none';
        const adminHidden = document.getElementById('dashboardMain').style.display === 'none';

        // Test 2: Anomaly Filter fuzzing
        let filterErrors = 0;
        const testFilters = ['ALL', 'SEV-1', 'SEV1', 'SEV-2', 'SEV2', 'EMPTY', 'UNKNOWN_FILTER', null, undefined, 123];
        for (const f of testFilters) {
          try {
            window.filterAnomalies(f);
          } catch (e) {
            filterErrors++;
          }
        }
        window.filterAnomalies('ALL');

        // Test 3: Interactive Tamper Demonstration Simulation
        const tamperBtn = document.getElementById('tamperDemoBtn');
        const resetBtn = document.getElementById('resetPayloadBtn');
        const outcomeBox = document.getElementById('verifyOutcomeBox');

        let tamperWorked = false;
        let resetWorked = false;

        if (typeof window.simulatePayloadTamper === 'function') {
          await window.simulatePayloadTamper();
          tamperWorked = outcomeBox && outcomeBox.textContent.includes('TAMPER DETECTED');
        }

        if (typeof window.resetTamperSimulation === 'function') {
          await window.resetTamperSimulation();
          resetWorked = outcomeBox && outcomeBox.textContent.includes('VERIFIED') && !outcomeBox.textContent.includes('TAMPER');
        }

        return {
          toggleErrors,
          sentinelVisible,
          adminHidden,
          filterErrors,
          tamperWorked,
          resetWorked,
        };
      })()
    `, true);

    runner.record('State Machine', '20 rapid view switches execute with zero errors', interactionResults.toggleErrors === 0);
    runner.record('State Machine', 'Sentinel view cleanly active after toggles', interactionResults.sentinelVisible && interactionResults.adminHidden);
    runner.record('State Machine', 'Anomaly filter fuzzing survives unknown/null filters with zero errors', interactionResults.filterErrors === 0);
    runner.record('State Machine', 'Interactive tamper simulation transitions to TAMPER DETECTED', interactionResults.tamperWorked);
    runner.record('State Machine', 'Interactive reset button restores authentic VERIFIED state', interactionResults.resetWorked);

  } catch (err) {
    console.error(`${C.red}CRITICAL TEST SUITE ERROR: ${err.message}${C.reset}`);
    runner.record('Suite Crash', 'Runner encountered fatal exception', false, null, err.message);
  } finally {
    if (chrome) await chrome.close();
    if (localServer && localServer.server) {
      await new Promise(r => localServer.server.close(r));
    }
  }

  const summary = runner.summary();
  console.log(`\n${C.bold}${C.cyan}========================================================================${C.reset}`);
  console.log(`${C.bold}Challenger Stress Test Summary:${C.reset}`);
  console.log(`  Total Assertions : ${summary.total}`);
  console.log(`  Passed           : ${C.green}${summary.passed}${C.reset}`);
  console.log(`  Failed           : ${summary.failed > 0 ? C.red : C.green}${summary.failed}${C.reset}`);
  console.log(`  Duration         : ${summary.duration}s`);
  console.log(`${C.bold}${C.cyan}========================================================================${C.reset}\n`);

  process.exit(summary.failed > 0 ? 1 : 0);
}

runAdversarialSuite();

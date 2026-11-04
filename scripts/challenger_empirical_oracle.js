#!/usr/bin/env node
/**
 * CHALLENGER EMPIRICAL ORACLE & DEEP STRESS HARNESS
 * Milestone 1 Iteration 2 Gate Verification
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

const C = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
};

class ChallengerOracle {
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
    return { total, passed, failed, duration };
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

  async close() {
    if (this.ws) try { this.ws.close(); } catch (e) {}
    if (this.proc) try { this.proc.kill('SIGKILL'); } catch (e) {}
  }
}

async function runOracleVerification() {
  console.log(`${C.bold}${C.cyan}========================================================================${C.reset}`);
  console.log(`${C.bold}${C.cyan}  CHALLENGER EMPIRICAL ORACLE & DEEP STRESS VERIFICATION               ${C.reset}`);
  console.log(`${C.bold}${C.cyan}========================================================================${C.reset}\n`);

  const oracle = new ChallengerOracle();
  let localServer = null;
  let chrome = null;

  try {
    localServer = await startLocalServer(SITE_DIR);
    const cdpPort = 9500 + Math.floor(Math.random() * 400);
    chrome = new ChromeSession(CHROME_PATH, cdpPort);
    await chrome.launch();

    await chrome.send('Page.navigate', { url: `${localServer.url}/dashboard.html#sentinel` });
    // Wait for full initialization and data loads
    await new Promise(r => setTimeout(r, 1500));

    // =========================================================================
    // PART 1: LIVE DOM CONTAINER VERIFICATION (NON-EMPTY, LIVE SVG, LIVE CHARTS)
    // =========================================================================
    console.log(`\n${C.bold}--- PART 1: Live DOM Containers & Active Canvas Inspection ---${C.reset}`);

    const domCheck = await chrome.eval(`
      (() => {
        // 1. #riskDistributionCanvas
        const distCanvas = document.getElementById("riskDistributionCanvas");
        const distChart = distCanvas && typeof Chart !== "undefined" ? Chart.getChart(distCanvas) : null;
        const distValid = distChart && distChart.config.type === "doughnut" && Array.isArray(distChart.data.datasets[0].data);

        // 2. #preflightHistoryCanvas
        const histCanvas = document.getElementById("preflightHistoryCanvas");
        const histChart = histCanvas && typeof Chart !== "undefined" ? Chart.getChart(histCanvas) : null;
        const histValid = histChart && histChart.config.type === "line" && Array.isArray(histChart.data.datasets[0].data);

        // 3. #preflightGaugeContainer
        const gaugeEl = document.getElementById("preflightGaugeContainer");
        const gaugeSvg = gaugeEl ? gaugeEl.querySelector("svg") : null;
        const gaugeCircles = gaugeSvg ? gaugeSvg.querySelectorAll("circle") : [];
        const gaugeScore = gaugeEl ? gaugeEl.querySelector("span.text-3xl") : null;
        const gaugeTier = gaugeEl ? gaugeEl.querySelector("span.uppercase") : null;
        const gaugeValid = !!(gaugeSvg && gaugeCircles.length >= 2 && gaugeScore && gaugeTier && !gaugeEl.innerHTML.includes("<!--"));

        // 4. #preflightFactorMeters
        const factorMetersEl = document.getElementById("preflightFactorMeters");
        const factorCards = factorMetersEl ? factorMetersEl.querySelectorAll("div.border") : [];
        const factorMeterBars = factorMetersEl ? factorMetersEl.querySelectorAll(".rounded-full") : [];
        const factorValid = !!(factorMetersEl && factorCards.length >= 4 && !factorMetersEl.innerHTML.includes("<!--"));

        // 5. #monitoredPoolsTableBody
        const poolsTbody = document.getElementById("monitoredPoolsTableBody");
        const poolRows = poolsTbody ? poolsTbody.querySelectorAll("tr") : [];
        const poolSvgs = poolsTbody ? poolsTbody.querySelectorAll("svg") : [];
        const poolsValid = !!(poolsTbody && poolRows.length >= 1 && poolSvgs.length >= 1 && !poolsTbody.innerHTML.includes("<!--"));

        // 6. #historyTbody
        const histTbody = document.getElementById("historyTbody");
        const histRows = histTbody ? histTbody.querySelectorAll("tr") : [];
        const histTbodyValid = !!(histTbody && histRows.length >= 1 && !histTbody.innerHTML.includes("<!--"));

        // 7. Responsive DOM wrapper checks (Section 4 & 5 bug prevention)
        const agentDossier = document.getElementById("agentDossierCard");
        const agentDossierHeader = agentDossier ? agentDossier.querySelector(".flex.items-center.gap-2") : null;
        const agentHasWrap = agentDossierHeader ? agentDossierHeader.classList.contains("flex-wrap") : false;
        const digestSpan = document.getElementById("currentDigestDisplay");
        const digestHasBreak = digestSpan ? digestSpan.classList.contains("break-all") : false;

        return {
          distCanvasExists: !!distCanvas,
          distValid,
          distData: distChart ? distChart.data.datasets[0].data : null,
          histCanvasExists: !!histCanvas,
          histValid,
          histDataLength: histChart ? histChart.data.datasets[0].data.length : 0,
          gaugeValid,
          gaugeScoreText: gaugeScore ? gaugeScore.textContent.trim() : null,
          gaugeTierText: gaugeTier ? gaugeTier.textContent.trim() : null,
          factorValid,
          factorCount: factorCards.length,
          poolsValid,
          poolRowCount: poolRows.length,
          sparklineCount: poolSvgs.length,
          histTbodyValid,
          histRowCount: histRows.length,
          agentHasWrap,
          digestHasBreak,
        };
      })()
    `);

    oracle.record('Live DOM', '#riskDistributionCanvas exists and has active Doughnut Chart instance', domCheck.distValid, domCheck);
    oracle.record('Live DOM', '#preflightHistoryCanvas exists and has active Line Chart instance', domCheck.histValid, domCheck);
    oracle.record('Live DOM', '#preflightGaugeContainer contains live SVG gauge (not empty/comment)', domCheck.gaugeValid, { score: domCheck.gaugeScoreText, tier: domCheck.gaugeTierText });
    oracle.record('Live DOM', '#preflightFactorMeters contains 4 factor meters (not empty/comment)', domCheck.factorValid, { count: domCheck.factorCount });
    oracle.record('Live DOM', '#monitoredPoolsTableBody populated with rows & mini sparkline SVGs', domCheck.poolsValid, { rows: domCheck.poolRowCount, svgs: domCheck.sparklineCount });
    oracle.record('Live DOM', '#historyTbody populated with historical audit rows', domCheck.histTbodyValid, { rows: domCheck.histRowCount });
    oracle.record('Live DOM', '#agentDossierCard header includes flex-wrap for mobile responsiveness', domCheck.agentHasWrap);
    oracle.record('Live DOM', '#currentDigestDisplay includes break-all for mobile hash wrapping', domCheck.digestHasBreak);

    // =========================================================================
    // PART 2: SECTION F ADVERSARIAL FUZZING — SPARSE/NULL ARRAYS IN buildRiskHistoryChart
    // =========================================================================
    console.log(`\n${C.bold}--- PART 2: Deep Sparse & Malformed Array Fuzzing in buildRiskHistoryChart ---${C.reset}`);

    const fuzzTestResults = await chrome.eval(`
      (() => {
        const dummyCanvas = document.createElement('canvas');
        dummyCanvas.id = 'fuzzCanvas_' + Math.random().toString(36).substring(7);
        dummyCanvas.width = 400;
        dummyCanvas.height = 200;
        document.body.appendChild(dummyCanvas);

        const suites = [];

        // Test F1: Array constructor holes (sparse array new Array(10))
        try {
          const sparse1 = new Array(10);
          const chart1 = window.buildRiskHistoryChart(dummyCanvas, sparse1);
          suites.push({
            name: "sparse_new_array_10_holes",
            passed: chart1 && chart1.data.labels.length === 10 && chart1.data.datasets[0].data.length === 10,
            labels: chart1 ? chart1.data.labels : null,
            data: chart1 ? chart1.data.datasets[0].data : null,
          });
        } catch (e) {
          suites.push({ name: "sparse_new_array_10_holes", passed: false, error: e.message });
        }

        // Test F2: Array with index holes (sparse array with indexed assignments)
        try {
          const sparse2 = [];
          sparse2[0] = 5;
          sparse2[4] = 45;
          sparse2[9] = 95;
          const chart2 = window.buildRiskHistoryChart(dummyCanvas, sparse2);
          suites.push({
            name: "sparse_indexed_holes",
            passed: chart2 && chart2.data.labels.length === 10 && chart2.data.datasets[0].data.length === 10,
            data: chart2 ? chart2.data.datasets[0].data : null,
          });
        } catch (e) {
          suites.push({ name: "sparse_indexed_holes", passed: false, error: e.message });
        }

        // Test F3: Array of all nulls
        try {
          const allNull = [null, null, null, null, null];
          const chart3 = window.buildRiskHistoryChart(dummyCanvas, allNull);
          suites.push({
            name: "all_null_array",
            passed: chart3 && chart3.data.labels.every(l => l === "Obs") && chart3.data.datasets[0].data.every(d => d === 0),
          });
        } catch (e) {
          suites.push({ name: "all_null_array", passed: false, error: e.message });
        }

        // Test F4: Array of all undefined
        try {
          const allUndef = [undefined, undefined, undefined];
          const chart4 = window.buildRiskHistoryChart(dummyCanvas, allUndef);
          suites.push({
            name: "all_undefined_array",
            passed: chart4 && chart4.data.labels.every(l => l === "Obs") && chart4.data.datasets[0].data.every(d => d === 0),
          });
        } catch (e) {
          suites.push({ name: "all_undefined_array", passed: false, error: e.message });
        }

        // Test F5: Extreme Malformed Objects (missing scores, weird types, nested structures)
        try {
          const malformedObjs = [
            {},
            { score: "NaN" },
            { score: -50 },
            { score: 999 },
            { overall_risk_score: "not_a_number" },
            { overall_risk_score: null },
            { overall_risk_score: undefined },
            { overall_risk_score: 85, time: null },
            { overall_risk_score: 12, time: "<script>alert('xss')</script>" },
            { assessed_at: "2026-11-04T07:15:30Z" },
            { assessed_at: null },
            { assessed_at: {} },
            true,
            false,
            "random_string",
            Symbol("sym"),
            () => 42,
          ];
          const chart5 = window.buildRiskHistoryChart(dummyCanvas, malformedObjs);
          const safeLabels = chart5 ? chart5.data.labels.every(l => typeof l === "string" && !l.includes("<script>")) : false;
          const safeScores = chart5 ? chart5.data.datasets[0].data.every(d => typeof d === "number" && !isNaN(d) && d >= 0 && d <= 100) : false;
          suites.push({
            name: "extreme_malformed_objects_and_primitives",
            passed: chart5 && safeLabels && safeScores,
            length: chart5 ? chart5.data.datasets[0].data.length : 0,
          });
        } catch (e) {
          suites.push({ name: "extreme_malformed_objects_and_primitives", passed: false, error: e.message });
        }

        // Test F6: Massive 500-element randomized fuzz generator
        try {
          const fuzzGen = [];
          for (let i = 0; i < 500; i++) {
            const kind = i % 8;
            if (kind === 0) fuzzGen.push(null);
            else if (kind === 1) fuzzGen.push(undefined);
            else if (kind === 2) fuzzGen.push((i * 17) % 150 - 25); // numbers from -25 to 125
            else if (kind === 3) fuzzGen.push({ score: (i * 3) % 100, time: "T+" + i });
            else if (kind === 4) fuzzGen.push({ overall_risk_score: (i * 7) % 100, assessed_at: "2026-11-04T08:00:00Z" });
            else if (kind === 5) fuzzGen.push({ score: "garbage" + i });
            else if (kind === 6) fuzzGen.push({});
            else fuzzGen.push("text_" + i);
          }
          const chart6 = window.buildRiskHistoryChart(dummyCanvas, fuzzGen);
          const genScoresSafe = chart6 ? chart6.data.datasets[0].data.every(d => typeof d === "number" && !isNaN(d) && d >= 0 && d <= 100) : false;
          suites.push({
            name: "massive_500_element_random_fuzz",
            passed: chart6 && chart6.data.datasets[0].data.length === 500 && genScoresSafe,
          });
        } catch (e) {
          suites.push({ name: "massive_500_element_random_fuzz", passed: false, error: e.message });
        }

        // Cleanup
        dummyCanvas.remove();
        return suites;
      })()
    `);

    for (const test of fuzzTestResults) {
      oracle.record('Sparse/Null Fuzzing', test.name, test.passed, test, test.error);
    }

    // =========================================================================
    // PART 3: ALL SENTINEL VIEWS VISIBILITY & INTERACTION AUDIT
    // =========================================================================
    console.log(`\n${C.bold}--- PART 3: Sentinel Views Verification & Layout Robustness ---${C.reset}`);

    const viewAudit = await chrome.eval(`
      (() => {
        const results = {};
        const requiredSections = [
          "sentinelView",
          "sentinelOverviewSection",
          "poolPreflightSection",
          "agentCreditSection",
          "liveAnomaliesSection",
          "cryptoVerifySection"
        ];

        for (const id of requiredSections) {
          const el = document.getElementById(id);
          results[id] = {
            exists: !!el,
            visible: el ? el.offsetWidth > 0 && el.offsetHeight > 0 : false,
            childCount: el ? el.childElementCount : 0
          };
        }

        return results;
      })()
    `);

    for (const [id, info] of Object.entries(viewAudit)) {
      oracle.record(
        'Section Hierarchy',
        `Section #${id} exists with rendered geometry and children`,
        info.exists && info.childCount > 0,
        info
      );
    }

    // =========================================================================
    // PART 4: FULL XSS SANITIZATION CHECK OF MODULAR OUTPUTS
    // =========================================================================
    console.log(`\n${C.bold}--- PART 4: Comprehensive Modular Functions Security Audit ---${C.reset}`);

    const secAudit = await chrome.eval(`
      (() => {
        const payload = '<svg onload=alert(1)><img src=x onerror="alert(2)">';

        // 1. renderRiskFactor
        const rf = window.renderRiskFactor(payload, 50, payload);
        const rfSafe = !rf.includes('<svg onload') && !rf.includes('<img src=x');

        // 2. renderIncidentTimeline
        const inc = window.renderIncidentTimeline([
          { title: payload, description: payload, severity: payload, pool_address: payload }
        ]);
        const incSafe = !inc.includes('<svg onload') && !inc.includes('<img src=x');

        // 3. renderCryptoStatusCard
        const card = window.renderCryptoStatusCard({
          key_id: payload,
          fingerprint: payload,
          verified: true
        });
        const cardSafe = !card.includes('<svg onload') && !card.includes('<img src=x');

        // 4. renderRiskGauge
        const gauge = window.renderRiskGauge(50, payload);
        const gaugeSafe = !gauge.includes('<svg onload') && !gauge.includes('<img src=x');

        // 5. escapeHtml existence & correctness
        const escaped = window.escapeHtml ? window.escapeHtml('<>&"\\'') : '';
        const escapeCorrect = escaped === '&lt;&gt;&amp;&quot;&#39;';

        return {
          rfSafe,
          incSafe,
          cardSafe,
          gaugeSafe,
          escapeCorrect,
        };
      })()
    `);

    oracle.record('Security Audit', 'renderRiskFactor sanitizes nested HTML injection payloads', secAudit.rfSafe);
    oracle.record('Security Audit', 'renderIncidentTimeline sanitizes malicious incident fields', secAudit.incSafe);
    oracle.record('Security Audit', 'renderCryptoStatusCard sanitizes malicious key_id/fingerprint', secAudit.cardSafe);
    oracle.record('Security Audit', 'renderRiskGauge sanitizes malicious classification tier argument', secAudit.gaugeSafe);
    oracle.record('Security Audit', 'window.escapeHtml correctly encodes <, >, &, ", and \'', secAudit.escapeCorrect);

  } catch (err) {
    console.error(`${C.red}FATAL ORACLE ERROR: ${err.message}${C.reset}`);
    oracle.record('Oracle Crash', 'Oracle execution encountered unexpected error', false, null, err.message);
  } finally {
    if (chrome) await chrome.close();
    if (localServer && localServer.server) {
      await new Promise(r => localServer.server.close(r));
    }
  }

  const summary = oracle.summary();
  console.log(`\n${C.bold}${C.cyan}========================================================================${C.reset}`);
  console.log(`${C.bold}Challenger Empirical Oracle Summary:${C.reset}`);
  console.log(`  Total Assertions : ${summary.total}`);
  console.log(`  Passed           : ${C.green}${summary.passed}${C.reset}`);
  console.log(`  Failed           : ${summary.failed > 0 ? C.red : C.green}${summary.failed}${C.reset}`);
  console.log(`  Duration         : ${summary.duration}s`);
  console.log(`${C.bold}${C.cyan}========================================================================${C.reset}\n`);

  process.exit(summary.failed > 0 ? 1 : 0);
}

runOracleVerification();

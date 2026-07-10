#!/usr/bin/env node
/**
 * examples/external_quote_subscriber.js
 *
 * EvTrade 行情订阅 Demo (JS / Node)
 * =====================================================================
 *
 * 演示两种订阅模式:
 *   模式 A: 全量订阅 (subscribe_all=true) → 后端 broadcast_to_stock() 对所有
 *            当前有 tick 的标的过滤推送,前端 ws 只要 send {type:"subscribe", stock_codes:[...]}
 *            即按订阅走
 *   模式 B: 按证券代码订阅 (subscribe_all=false + stock_codes=[...]) →
 *            只订阅指定代码,其他 tick 即使来了也收不到
 *
 * 用法:
 *   # 1. 全量模式 (默认订阅几个演示代码,后端只推这些;零订阅时没数据)
 *   node examples/external_quote_subscriber.js
 *
 *   # 2. 按证券代码模式
 *   node examples/external_quote_subscriber.js --mode=specific --codes=000001,600519,000333
 *
 *   # 3. 切换 base URL
 *   BASE_URL=http://192.168.1.100:8000 node examples/external_quote_subscriber.js
 *
 *   # 4. 不订阅任何代码 (验证"零订阅时静默丢弃",看 60 秒有没有数据)
 *   node examples/external_quote_subscriber.js --mode=none
 *
 *   # 5. JWT 调试 (跳过 login)
 *   JWT_TOKEN=eyJhbGc... node examples/external_quote_subscriber.js
 *
 * 依赖: ws (Node.js 库, 项目 client/node_modules 已装)
 * 运行: cd /root/workspcae/codespace/EvTrade && node examples/external_quote_subscriber.js
 *
 * 登录: quota / quota (viewer 角色, 行情 demo 专用账号)
 *
 * 退出: Ctrl+C 优雅关闭 (清理 ws + 退出)
 * =====================================================================
 */

const WebSocket = require("../client/node_modules/ws");

// ────────────────────── 配置区 ──────────────────────
const CONFIG = {
  baseUrl: process.env.BASE_URL || "http://127.0.0.1:8000",
  wsUrl: null, // 根据 baseUrl 推导
  username: process.env.USERNAME || "quota",
  password: process.env.PASSWORD || "quota",
  // 演示用 codes (可在 CLI 覆盖)
  defaultCodes: ["000001", "600519", "000333", "000858", "601318"],
  // 收集时长 (秒) — 收到 N 条 tick 或超时后自动退出,打印统计
  collectSeconds: parseInt(process.env.COLLECT_SECONDS || "12", 10),
  // 打印频率 — 防止刷屏, 默认每个标的第一条 + 每秒心跳
  heartbeatSec: 5,
};

// ────────────────────── CLI 参数解析 ──────────────────────
function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { mode: "specific", codes: CONFIG.defaultCodes };
  for (const a of args) {
    if (a.startsWith("--mode=")) opts.mode = a.split("=")[1];
    else if (a.startsWith("--codes=")) {
      opts.codes = a.split("=")[1].split(",").map((c) => c.trim()).filter(Boolean);
    }
  }
  // 全量模式: codes=["*"] 等价于"订阅默认 demo 列表"
  if (opts.mode === "all") opts.codes = CONFIG.defaultCodes;
  if (opts.mode === "none") opts.codes = [];
  return opts;
}

// ────────────────────── 工具 ──────────────────────
function ts() {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

function log(level, msg) {
  const colors = { INFO: "\x1b[36m", OK: "\x1b[32m", WARN: "\x1b[33m", ERR: "\x1b[31m", DIM: "\x1b[90m" };
  const c = colors[level] || "";
  const r = "\x1b[0m";
  console.log(`${c}[${level.padEnd(4)}]${r} [${ts()}] ${msg}`);
}

async function login(baseUrl, username, password) {
  const url = `${baseUrl}/api/auth/login`;
  log("INFO", `POST ${url} (form-data)`);
  // FastAPI OAuth2PasswordRequestForm 走 application/x-www-form-urlencoded
  const formBody = new URLSearchParams({ username, password });
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: formBody,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`login failed: HTTP ${res.status} ${text}`);
  }
  const body = await res.json();
  if (!body.access_token) throw new Error("login response missing access_token");
  log("OK", `login OK (role=${body.role || "?"}, sub=${body.user_id || "?"})`);
  return body.access_token;
}

function httpToWs(httpUrl) {
  return httpUrl.replace(/^http/, "ws") + "/ws/quote_update";
}

// ────────────────────── 主流程 ──────────────────────
async function main() {
  const opts = parseArgs();
  CONFIG.wsUrl = httpToWs(CONFIG.baseUrl);

  log("INFO", `=== EvTrade 行情订阅 Demo ===`);
  log("INFO", `base URL:    ${CONFIG.baseUrl}`);
  log("INFO", `ws URL:      ${CONFIG.wsUrl}`);
  log("INFO", `mode:        ${opts.mode}`);
  log("INFO", `codes:       [${opts.codes.join(", ")}] (${opts.codes.length} codes)`);
  log("INFO", `collect:     ${CONFIG.collectSeconds}s`);
  console.log("");

  // 1. 登录 (如果 env 没传 JWT)
  let token = process.env.JWT_TOKEN;
  if (!token) {
    token = await login(CONFIG.baseUrl, CONFIG.username, CONFIG.password);
  } else {
    log("INFO", `use JWT_TOKEN from env (skip login)`);
  }

  // 2. 建 WS 连接
  const wsUrlWithToken = `${CONFIG.wsUrl}?token=${encodeURIComponent(token)}`;
  log("INFO", `connecting to WS ...`);
  const ws = new WebSocket(wsUrlWithToken);
  let connected = false;
  let subscribed = false;

  // 统计
  const stats = {
    connectTs: 0,
    subscribeTs: 0,
    ticksByCode: new Map(), // code → [{ts, last_price, count}]
    totalTicks: 0,
    sampleMsgs: [], // 前 5 条原始消息
    pings: 0,
  };

  return new Promise((resolve, reject) => {
    // 收集超时
    const collectTimer = setTimeout(() => {
      log("WARN", `collect timeout (${CONFIG.collectSeconds}s)`);
      finish("timeout");
    }, CONFIG.collectSeconds * 1000);

    function finish(reason) {
      clearTimeout(collectTimer);
      clearInterval(heartbeatTimer);
      printSummary(reason);
      try { ws.close(); } catch {}
      resolve();
    }

    function printSummary(reason) {
      console.log("");
      log("OK", `=== Summary (reason=${reason}) ===`);
      log("INFO", `connected:           ${connected ? "yes" : "no"}`);
      log("INFO", `subscribed:          ${subscribed ? "yes" : "no"}`);
      log("INFO", `total ticks:         ${stats.totalTicks}`);
      log("INFO", `unique codes:        ${stats.ticksByCode.size}`);
      log("INFO", `server pings recv:   ${stats.pings}`);
      if (stats.connectTs && stats.subscribeTs) {
        log("INFO", `connect→subscribe:   ${stats.subscribeTs - stats.connectTs}ms`);
      }
      if (stats.ticksByCode.size > 0) {
        const sorted = [...stats.ticksByCode.entries()].sort((a, b) => b[1].length - a[1].length);
        console.log("");
        console.log("\x1b[36m┌─────────────┬───────┬───────────┬──────────────┐\x1b[0m");
        console.log("\x1b[36m│ stock_code  │ ticks │ last px   │ first ts     │\x1b[0m");
        console.log("\x1b[36m├─────────────┼───────┼───────────┼──────────────┤\x1b[0m");
        for (const [code, ticks] of sorted) {
          const last = ticks[ticks.length - 1].last_price;
          const firstTs = new Date(ticks[0].ts).toLocaleTimeString("zh-CN", { hour12: false });
          console.log(
            `\x1b[36m│\x1b[0m ${code.padEnd(11)} \x1b[36m│\x1b[0m ${String(ticks.length).padStart(5)} \x1b[36m│\x1b[0m ${(last || 0).toFixed(3).padStart(9)} \x1b[36m│\x1b[0m ${firstTs} \x1b[36m│\x1b[0m`
          );
        }
        console.log("\x1b[36m└─────────────┴───────┴───────────┴──────────────┘\x1b[0m");
      } else {
        log("WARN", `no ticks received`);
        log("INFO", `如果这是 mode=none, 这是预期 (验证零订阅静默丢弃)`);
        log("INFO", `如果这是 mode=specific/all, 检查: 1) hqserver 在跑 2) 代码在 tick 数据源里`);
      }
      if (stats.sampleMsgs.length > 0) {
        console.log("");
        log("INFO", `前 ${stats.sampleMsgs.length} 条原始消息 (msg.type 维度):`);
        for (const m of stats.sampleMsgs) {
          const dataStr = JSON.stringify(m.data || m).slice(0, 120);
          console.log(`  ${m.type.padEnd(20)} ${dataStr}${dataStr.length >= 120 ? "..." : ""}`);
        }
      }
    }

    // 心跳日志
    const heartbeatTimer = setInterval(() => {
      const secs = ((Date.now() - stats.connectTs) / 1000).toFixed(0);
      log("DIM", `[tick=${stats.totalTicks} codes=${stats.ticksByCode.size}] running ${secs}s ...`);
    }, CONFIG.heartbeatSec * 1000);

    ws.on("open", () => {
      connected = true;
      stats.connectTs = Date.now();
      log("OK", `WS connected (pid=${process.pid})`);

      // 3. 订阅
      const msg = { type: "subscribe", stock_codes: opts.codes };
      log("INFO", `send subscribe: ${JSON.stringify(msg)}`);
      ws.send(JSON.stringify(msg));
      subscribed = true;
      stats.subscribeTs = Date.now();
    });

    ws.on("message", (raw) => {
      let msg;
      try { msg = JSON.parse(raw.toString()); } catch { return; }

      // 记录原始样本
      if (stats.sampleMsgs.length < 5) stats.sampleMsgs.push(msg);

      if (msg.type === "ping") {
        stats.pings++;
        // 不打印,太刷屏
        return;
      }

      if (msg.type === "quote" && msg.data) {
        const tick = msg.data;
        const code = tick.stock_code || msg.channel || "?";
        const last = tick.last_price;
        stats.totalTicks++;
        if (!stats.ticksByCode.has(code)) stats.ticksByCode.set(code, []);
        const arr = stats.ticksByCode.get(code);
        if (arr.length === 0 || Date.now() - arr[arr.length - 1].ts > 500) {
          // 第一条 或距上一条 >500ms → 记录(避免刷屏)
          arr.push({ ts: Date.now(), last_price: last });
        } else {
          // 静默更新最后一条的 last_price
          arr[arr.length - 1].last_price = last;
        }
        // 实时打印(简化版,避免刷屏)
        log("INFO", `tick ${code} last=${(last || 0).toFixed(3)} bid1=${tick.bid1_price || 0} ask1=${tick.ask1_price || 0}`);
        return;
      }

      if (msg.type === "subscribe_ack") {
        log("OK", `subscribe_ack: ${JSON.stringify(msg).slice(0, 200)}`);
        return;
      }

      // 其他类型
      log("DIM", `recv msg.type=${msg.type}: ${JSON.stringify(msg).slice(0, 100)}`);
    });

    ws.on("error", (err) => {
      log("ERR", `WS error: ${err.message}`);
      finish("error");
    });

    ws.on("close", (code, reason) => {
      log("WARN", `WS closed: code=${code} reason=${reason.toString().slice(0, 50)}`);
      finish("close");
    });

    // Ctrl+C
    process.on("SIGINT", () => {
      log("WARN", `SIGINT received`);
      finish("sigint");
    });
  });
}

main()
  .then(() => {
    log("OK", `demo done`);
    process.exit(0);
  })
  .catch((err) => {
    log("ERR", `fatal: ${err.message}`);
    console.error(err);
    process.exit(1);
  });
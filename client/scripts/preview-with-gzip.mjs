#!/usr/bin/env node
/**
 * preview-with-gzip.mjs — EvTrade 生产预览服务器 (frontend-initial-load-perf Phase 2)
 *
 * 替代 `vite preview`,理由:
 * - vite preview 默认不启用 gzip,而 client/dist/index-*.js 1.33 MB raw 浏览器下载慢
 * - nginx/openresty 中间层可能不带 gzip 配置
 * - 此脚本用纯 Node 标准库 (http + zlib + fs + path) 启 HTTP server,
 *   自动按 Accept-Encoding: gzip 对 .js / .css / .html / .json / .svg 等文本资源做流式 gzip 压缩
 *   gzipped 后 ~67% 体积下降 (1.33 MB → 431 KB)
 *
 * 启动:
 *   node preview-with-gzip.mjs --port 50998 --host 0.0.0.0 --root ../dist
 */
import http from 'node:http'
import { createReadStream, statSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { request as httpRequest } from 'node:http'
import zlib from 'node:zlib'

// ---- 后端反代 (等价 vite dev 的 server.proxy 配置) ----
// fix 2026-10-19: vite preview 没有 server.proxy, /api 全部走 SPA fallback 返回 index.html
//   → axios 拿到 HTML 字符串 → res.access_token undefined → tokenStorage.set(undefined)
//   → localStorage 存了字符串 "undefined" → ws URL ?token=undefined → 登录后不跳转
// vite.config.js server.proxy: '/api' → http://localhost:8000, '/ws' → ws://localhost:8000
const API_TARGET = { host: '127.0.0.1', port: 8000 }

// ---- CLI ----
const args = process.argv.slice(2)
function getArg(name, def) {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def
}

const HOST = getArg('--host', '0.0.0.0')
const PORT = parseInt(getArg('--port', '50998'), 10)
const SCRIPT_DIR = fileURLToPath(new URL('.', import.meta.url))
const ROOT = resolve(getArg('--root', join(SCRIPT_DIR, '..', 'dist')))

const COMPRESSIBLE = new Set([
  '.js', '.mjs', '.css', '.html', '.json', '.svg', '.xml',
  '.txt', '.wasm',
])

const MIME = {
  '.js': 'text/javascript',
  '.mjs': 'text/javascript',
  '.css': 'text/css',
  '.html': 'text/html',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.xml': 'application/xml',
  '.txt': 'text/plain',
  '.wasm': 'application/wasm',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
}

function mimeOf(p) {
  return MIME[extname(p).toLowerCase()] || 'application/octet-stream'
}

// 安全路径校验 — 防止 ../ 越权
function safeResolve(relPath) {
  const clean = normalize(relPath).replace(/^[/\\]+/, '')
  const full = resolve(join(ROOT, clean))
  if (!full.startsWith(ROOT)) return null
  return full
}

function shouldCompress(headers, filePath) {
  const accept = (headers['accept-encoding'] || '').toLowerCase()
  const ext = extname(filePath).toLowerCase()
  if (!COMPRESSIBLE.has(ext)) return false
  if (accept.includes('br')) return 'br'
  if (accept.includes('gzip')) return 'gzip'
  return false
}

function noCacheHeaders() {
  return {
    'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
  }
}

const server = http.createServer((req, res) => {
  const rawPath = req.url.split('?')[0]

  // ---- 后端反代: /api/* → backend:8000 ----
  // (vite preview 不带 server.proxy, 必须自建; 见文件头 fix 2026-10-19 注释)
  if (rawPath === '/api' || rawPath.startsWith('/api/')) {
    const proxyReq = httpRequest(
      {
        hostname: API_TARGET.host,
        port: API_TARGET.port,
        method: req.method,
        path: req.url,
        headers: { ...req.headers, host: `${API_TARGET.host}:${API_TARGET.port}` },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode || 502, proxyRes.headers)
        proxyRes.pipe(res)
      }
    )
    proxyReq.on('error', (err) => {
      console.error('[preview-with-gzip] /api proxy error:', err.message)
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json' })
      }
      res.end(JSON.stringify({ detail: 'backend unavailable: ' + err.message }))
    })
    req.pipe(proxyReq)
    return
  }

  // ---- WebSocket 反代: /ws/* → backend:8000 (upgrade 在 server.on('upgrade') 处理) ----
  // HTTP GET /ws/* (非 upgrade) 直接 426 Upgrade Required, 不进 SPA fallback
  if (rawPath === '/ws' || rawPath.startsWith('/ws/')) {
    res.writeHead(426, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ detail: 'WebSocket upgrade required' }))
    return
  }

  let urlPath = rawPath
  if (urlPath === '/') urlPath = '/index.html'

  let absPath = safeResolve(urlPath)
  if (!absPath) {
    res.writeHead(403); res.end('Forbidden'); return
  }

  let stat
  try {
    stat = statSync(absPath)
  } catch {
    // SPA fallback (vue-router history 模式): /foo 找不到 → /index.html
    absPath = join(ROOT, 'index.html')
    try {
      stat = statSync(absPath)
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain' })
      res.end('404 Not Found: ' + req.url)
      return
    }
  }

  if (stat.isDirectory()) {
    absPath = join(absPath, 'index.html')
    try { stat = statSync(absPath) } catch {
      res.writeHead(404); res.end('404 Not Found'); return
    }
  }

  const mime = mimeOf(absPath)
  const compressType = shouldCompress(req.headers, absPath)
  const baseHeaders = {
    'Content-Type': mime + '; charset=utf-8',
    'Content-Length': String(stat.size),
    ...noCacheHeaders(),
  }

  if (!compressType) {
    res.writeHead(200, baseHeaders)
    createReadStream(absPath).pipe(res)
    return
  }

  delete baseHeaders['Content-Length']
  const headers = {
    ...baseHeaders,
    'Content-Encoding': compressType,
    'Vary': 'Accept-Encoding',
    'Transfer-Encoding': 'chunked',
  }
  res.writeHead(200, headers)

  const compressStream = compressType === 'br'
    ? zlib.createBrotliCompress()
    : zlib.createGzip()

  createReadStream(absPath)
    .on('error', (err) => {
      console.error('[preview-with-gzip] file read error:', err.message)
      try { res.destroy(err) } catch (_) { /* ignore */ }
    })
    .pipe(compressStream)
    .on('error', (err) => {
      console.error('[preview-with-gzip] compress error:', err.message)
      try { res.destroy(err) } catch (_) { /* ignore */ }
    })
    .pipe(res)
})

server.listen(PORT, HOST, () => {
  console.log(`[preview-with-gzip] serving ${ROOT}`)
  console.log(`[preview-with-gzip] listening http://${HOST}:${PORT}`)
})

// ---- WebSocket upgrade 反代: /ws/* → backend:8000 ----
// fix 2026-10-19: vite preview 不代理 WS, 补上后 ws_heartbeat 的 5 个 channel 才能连通
server.on('upgrade', (req, socket, head) => {
  const rawPath = (req.url || '').split('?')[0]
  if (rawPath !== '/ws' && !rawPath.startsWith('/ws/')) {
    socket.destroy()
    return
  }
  const upstream = httpRequest({
    hostname: API_TARGET.host,
    port: API_TARGET.port,
    method: req.method,
    path: req.url,
    headers: { ...req.headers, host: `${API_TARGET.host}:${API_TARGET.port}` },
  })
  upstream.on('upgrade', (proxyRes, proxySocket, proxyHead) => {
    const lines = Object.entries(proxyRes.headers).map(
      ([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`
    )
    socket.write(`HTTP/1.1 101 Switching Protocols\r\n${lines.join('\r\n')}\r\n\r\n`)
    if (proxyHead && proxyHead.length) socket.unshift(proxyHead)
    proxySocket.pipe(socket).pipe(proxySocket)
  })
  upstream.on('response', (proxyRes) => {
    // 后端拒绝 upgrade (401/403) → 回 HTTP 状态给客户端
    socket.write(`HTTP/1.1 ${proxyRes.statusCode} ${proxyRes.statusMessage}\r\n\r\n`)
    socket.destroy()
  })
  upstream.on('error', (err) => {
    console.error('[preview-with-gzip] /ws upgrade error:', err.message)
    socket.destroy()
  })
  if (head && head.length) upstream.write(head)
  upstream.end()
})

process.on('SIGTERM', () => server.close(() => process.exit(0)))
process.on('SIGINT', () => server.close(() => process.exit(0)))

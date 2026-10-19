#!/usr/bin/env node
/**
 * preview-with-gzip.mjs — EvTrade 生产预览服务器 (frontend-initial-load-perf Phase 2)
 *
 * 替代 `vite preview`,理由:
 * - vite preview 默认不启用 gzip,而 client/dist/index-*.js 1.33 MB raw 浏览器下载慢
 * - nginx/openresty 中间层可能不带 gzip(gzip_types / gzip on) 配置
 * - 此脚本用纯 Node 标准库 (http + zlib + fs + path) 启 HTTP server,自动按 Accept-Encoding: gzip
 *   对 .js / .css / .html / .json / .svg 等文本类资源做流式 gzip 压缩
 *   gzipped 后 ~67% 体积下降 (1.33 MB → 431 KB)
 *
 * 启动:
 *   node preview-with-gzip.mjs --port 50998 --host 0.0.0.0 --root ../dist
 *
 * 2026-10-18 实现,与 evctl.py 集成 (env EVTRADE_FRONTEND_MODE=prod 时启用)
 */
import http from 'node:http'
import { createReadStream, statSync } from 'node:fs'
import { extname, join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import zlib from 'node:zlib'

// ---- CLI ----
const args = process.argv.slice(2)
function getArg(name, def) {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def
}

const HOST = getArg('--host', '0.0.0.0')
const PORT = parseInt(getArg('--port', '50998'), 10)
const SCRIPT_DIR = fileURLToPath(new URL('.', import.meta.url))
// 默认 dist 在脚本同目录上级: client/scripts/preview-with-gzip.mjs → client/dist/
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
  let urlPath = req.url.split('?')[0]
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

  // 不压缩 → 直接走 stream response (无 Transfer-Encoding)
  if (!compressType) {
    res.writeHead(200, baseHeaders)
    createReadStream(absPath).pipe(res)
    return
  }

  // 压缩路径 — streaming compress + chunked transfer
  // 不带 Content-Length (Chrome 会忽略),让 chunked 表达
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

process.on('SIGTERM', () => server.close(() => process.exit(0)))
process.on('SIGINT', () => server.close(() => process.exit(0)))

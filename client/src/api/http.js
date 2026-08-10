/**
 * client/src/api/http.js — HTTP 基础设施 (axios + 拦截器 + token 管理)
 *
 * 职责分离（D.1）:
 *   - http.js: axios 实例 + request/response 拦截器 + token 存储 + 401 处理
 *   - index.js: 业务 endpoint（holdings / orders / auth / ...）
 *
 * 业务代码按就近 import 原则选择:
 *   - 业务 endpoint: from './index' (or '../api' / '../../api')
 *   - http/tokenStorage: from './http' (or '../api/http' / '../../api/http')
 */
import axios from 'axios'
import { makeLogger } from '../utils/logger'

const log = makeLogger('api')

const API_BASE = '/api'
const TOKEN_KEY = 'evtrade-token'

// ============================================================
// Axios 实例 + 拦截器
// ============================================================
export const http = axios.create({
  baseURL: API_BASE,
  timeout: 15000
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 全局回调：401 时由路由层处理
let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

// 后端 RPC 响应统一为 {code, msg, list}：
//   - code === 0：把 res.data 替换为 list，调用方拿到的就是数组
//   - code !== 0：红色 ElMessage.error(msg) 并 reject，调用方 await 抛错
// 异步加载 element-plus 以避免与 main.js 的初始化循环依赖。
function _isRpcResponse(body) {
  return (
    body &&
    typeof body === 'object' &&
    !Array.isArray(body) &&
    'code' in body &&
    'msg' in body &&
    ('list' in body || 'data' in body)
  )
}

async function _showRpcError(msg) {
  try {
    const { ElMessage } = await import('element-plus')
    ElMessage.error(msg || '请求失败')
  } catch (e) {
    // eslint-disable-next-line no-console
    log.error('failed to show ElMessage:', e)
  }
}

http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (_isRpcResponse(body)) {
      const code = Number(body.code)
      if (code !== 0) {
        _showRpcError(body.msg)
        return Promise.reject({ rpc: true, code, msg: body.msg })
      }
      // 解包：统一返回 list 数组；兼容旧 data 字段
      if (Array.isArray(body.list)) {
        res.data = body.list
      } else if (body.data != null) {
        res.data = body.data
      } else {
        res.data = body
      }
    }
    return res
  },
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (onUnauthorized) onUnauthorized()
    }
    // 屏障/拒绝类 (403/422/500/503): FastAPI HTTPException 走 detail
    // 提取 detail.code + detail.msg 弹 ElMessage, 不然前端只看到 console 裸 503
    if (status && status >= 400) {
      const detail = err.response?.data?.detail
      let msg = null
      if (typeof detail === 'string') {
        msg = detail
      } else if (detail && typeof detail === 'object') {
        msg = detail.msg || detail.code || null
      }
      if (msg) {
        _showRpcError(msg)
      } else if (status === 503) {
        // 兜底：503 业务没返 detail 时也给个提示
        _showRpcError('服务暂不可用 (503)，请稍后重试')
      }
    }
    return Promise.reject(err)
  }
)

// ============================================================
// Token 管理
// ============================================================
export const tokenStorage = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY)
}

export const API_CONFIG = {
  base: API_BASE,
  tokenKey: TOKEN_KEY
}
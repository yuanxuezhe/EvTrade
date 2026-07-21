/**
 * api/sysconfig.js — 统一配置 CRUD (v78)
 */
import http from './http'

export const sysconfigApi = {
  /** 列出配置 (当前用户 + 继承默认) */
  list(user) {
    const url = user ? `/api/sysconfig?user=${encodeURIComponent(user)}` : '/api/sysconfig'
    return http.get(url)
  },
  /** 读单个 */
  get(cfg_key, user) {
    const url = user ? `/api/sysconfig/${cfg_key}?user=${encodeURIComponent(user)}` : `/api/sysconfig/${cfg_key}`
    return http.get(url)
  },
  /** 新增或更新 */
  upsert({ user, cfg_key, cfg_val, desc }) {
    return http.post('/api/sysconfig', { user, cfg_key, cfg_val, desc })
  },
  /** 更新 (PUT) */
  update(cfg_key, { user, cfg_val, desc }) {
    const url = user ? `/api/sysconfig/${cfg_key}?user=${encodeURIComponent(user)}` : `/api/sysconfig/${cfg_key}`
    return http.put(url, { cfg_key, cfg_val, desc })
  },
  /** 删除 */
  remove(cfg_key, user) {
    const url = user ? `/api/sysconfig/${cfg_key}?user=${encodeURIComponent(user)}` : `/api/sysconfig/${cfg_key}`
    return http.delete(url)
  },
}
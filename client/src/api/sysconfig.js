/**
 * api/sysconfig.js — 统一配置 CRUD
 *
 * http instance baseURL='/api', 这里只写 path 后缀 (不要带 /api 前缀, 会拼成 /api/api/...)
 * 返回 res.data 而不是 res (admin.js 等其他 api 都是这么写的)
 */
import { http } from './index'

export const sysconfigApi = {
  /** 列出配置 (当前用户 + 继承默认) */
  async list(user) {
    const url = user ? `/sysconfig?user=${encodeURIComponent(user)}` : '/sysconfig'
    const res = await http.get(url)
    return res.data
  },
  /** 读单个 */
  async get(cfg_key, user) {
    let url = `/sysconfig/${encodeURIComponent(cfg_key)}`
    if (user) url += `?user=${encodeURIComponent(user)}`
    const res = await http.get(url)
    return res.data
  },
  /** 新增或更新 */
  async upsert({ user, cfg_key, cfg_val, desc }) {
    const res = await http.post('/sysconfig', { user, cfg_key, cfg_val, desc })
    return res.data
  },
  /** 更新 (PUT) */
  async update(cfg_key, { user, cfg_val, desc }) {
    let url = `/sysconfig/${encodeURIComponent(cfg_key)}`
    if (user) url += `?user=${encodeURIComponent(user)}`
    const res = await http.put(url, { user, cfg_val, desc })
    return res.data
  },
  /** 删除 */
  async remove(cfg_key, user) {
    let url = `/sysconfig/${encodeURIComponent(cfg_key)}`
    if (user) url += `?user=${encodeURIComponent(user)}`
    const res = await http.delete(url)
    return res.data
  },
}

/**
 * roles API 客户端 (rbac-roles-module change 2026-09-21)
 *
 * 端点 (前缀 /api/roles, http baseURL 已含 /api, 路径不带 /api):
 * - GET    /roles                              列出所有角色 + 各自 page_keys
 * - GET    /roles/{id}                         单个角色详情
 * - POST   /roles                              新建角色
 * - PATCH  /roles/{id}                         改 display_name / description
 * - DELETE /roles/{id}                         删角色 (内置禁删)
 * - GET    /roles/{id}/permissions             该角色 page_keys 列表
 * - PUT    /roles/{id}/permissions             整体覆盖 page_keys
 * - GET    /roles/users/{user_id}/roles        用户已绑定角色
 * - PUT    /roles/users/{user_id}/roles        整体覆盖用户角色
 *
 * 鉴权: 全部 require_admin
 * 返回约定: 列表端点 → {list:[...]} (与 QuoteSyncApi.list 一致), 单点端点 → 对象本身
 */
import { http } from './http'

export const rolesApi = {
  /** 列所有角色 (含各自 page_keys) → {list: [{id,name,display_name,description,is_builtin,page_keys},...]} */
  list: () => http.get('/roles').then((r) => r.data),

  /** 单个角色详情 */
  get: (id) => http.get(`/roles/${id}`).then((r) => r.data),

  /** 新建角色 body: {name, display_name, description?, page_keys: []} → 返完整角色对象 */
  create: (data) => http.post('/roles', data).then((r) => r.data),

  /** 改 display_name / description (name 与 is_builtin 不可改) */
  update: (id, data) => http.patch(`/roles/${id}`, data).then((r) => r.data),

  /** 删角色 (内置 is_builtin=1 不能删) */
  remove: (id) => http.delete(`/roles/${id}`).then((r) => r.data),

  /** 该角色 page_keys 列表 → {role_id, role_name, permissions: [{page_key, granted_at}]} */
  getPermissions: (id) => http.get(`/roles/${id}/permissions`).then((r) => r.data),

  /** 整体覆盖该角色 page_keys body: {page_keys: [...]} */
  setPermissions: (id, pageKeys) =>
    http.put(`/roles/${id}/permissions`, { page_keys: pageKeys }).then((r) => r.data),

  /** 用户的角色详情 (含每个 role 的 page_keys) → {user_id, roles: [{id,name,display_name,is_builtin,page_keys}]} */
  getUserRoles: (userId) => http.get(`/roles/users/${userId}/roles`).then((r) => r.data),

  /** 整体覆盖用户角色 body: {role_names: ['trader','viewer']} */
  setUserRoles: (userId, roleNames) =>
    http.put(`/roles/users/${userId}/roles`, { role_names: roleNames }).then((r) => r.data),
}
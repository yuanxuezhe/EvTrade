// useUserActions.js — Users.vue 的弹窗状态 + 业务 action 抽离
//
// 将弹窗状态（visible / loading / form）+ open* / submit* 方法
// 集中到 composable，让 Users.vue 主壳只管表格 + 列表状态。
//
// formRef 由各弹窗组件内部自管（dialog 通过 watch(visible) 清校验），
// composable 调 dialog.validate() 走 dialog 暴露的方法。
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus/es'  // REQ-FE-553: 子路径避免整包 prebundle
import { userApi } from '../api'
import { rolesApi } from '../api/roles'


export function useUserActions() {
  // ===== dialog refs (由外部 Users.vue 通过 actions.dialogRefs.edit = ref 注入) =====
  // 不能用 reactive 包 ref — Vue 会自动 unwrap ref 到 .value, 导致 dialogRefs.edit
  // 直接是组件 instance, 而内部期望拿 ref 再 .value 才是 instance。
  // 用普通对象 + Vue 不会 unwrap, dialogRefs.edit 就是 ref 对象本身, .value 拿到组件 instance。
  const dialogRefs = { edit: null, pwd: null }

  // ===== 新建 / 编辑 弹窗 =====
  const editVisible = ref(false)
  const editLoading = ref(false)
  const editForm = reactive({
    id: null,
    username: '',
    password: '',
    // rbac-roles-module: 单 role 字符串保留 (向后兼容); 多角色用 role_names (整体覆盖)
    role: 'trader',
    role_names: [],  // 选中 RBAC 角色 name 列表 (空数组 = 无)
    email: '',
    full_name: '',
    is_active: true,
  })

  const editRules = {
    username: [
      { required: true, message: '请输入用户名', trigger: 'blur' },
      {
        validator: (_r, v, cb) =>
          /^[A-Za-z0-9_\-.]{3,32}$/.test(v) ? cb() : cb(new Error('3-32位字母/数字/_/-/.')),
        trigger: 'blur',
      },
    ],
    password: [
      { required: true, message: '请输入密码', trigger: 'blur' },
      { min: 6, message: '密码长度至少 6 位', trigger: 'blur' },
    ],
    role: [{ required: true, message: '请选择角色', trigger: 'change' }],
    email: [
      {
        validator: (_r, v, cb) =>
          !v || /^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(v) ? cb() : cb(new Error('邮箱格式不正确')),
        trigger: 'blur',
      },
    ],
  }

  function openCreate() {
    Object.assign(editForm, {
      id: null,
      username: '',
      password: '',
      role: 'trader',
      role_names: [],  // rbac-roles-module: 新建默认无 RBAC 角色 (等后端 seed 走完后 admin 再分配)
      email: '',
      full_name: '',
      is_active: true,
    })
    editVisible.value = true
  }

  async function openEdit(row) {
    Object.assign(editForm, {
      id: row.id,
      username: row.username,
      password: '',
      role: row.role,
      // rbac-roles-module: 从 row.roles 同步 RBAC 多角色 (admin 用户)
      role_names: Array.isArray(row.roles) ? row.roles.map(r => r.name) : [],
      email: row.email || '',
      full_name: row.full_name || '',
      is_active: row.is_active,
    })
    editVisible.value = true
  }

  async function submitEdit() {
    // dialogRefs.edit 由外部注入 (Users.vue: actions.dialogRefs.edit = editDialogEl)
    const dlgRef = dialogRefs.edit
    if (!dlgRef || !dlgRef.value) {
      console.error('[useUserActions] editDialogRef not injected by parent')
      return false
    }
    const valid = await dlgRef.value.validate().catch((err) => {
      console.debug('[useUserActions] form validate rejected:', err)
      return false
    })
    if (!valid) return false
    editLoading.value = true
    try {
      if (editForm.id) {
        // rbac-roles-module: 优先用 role_names (多角色) 覆盖; 老 role 字段保留
        // 后端 PATCH /users/{id} 支持 role_names (整体覆盖) + role (单字段, deprecated)
        await userApi.update(editForm.id, {
          role_names: editForm.role_names,
          email: editForm.email,
          full_name: editForm.full_name,
          is_active: editForm.is_active,
        })
        ElMessage.success('已保存')
      } else {
        // 新建: 后端 POST /users 仅支持 role 字符串 (rbac-roles-module 待 P6+ 改造)
        await userApi.create({
          username: editForm.username.trim(),
          password: editForm.password,
          role: editForm.role,
          email: editForm.email,
          full_name: editForm.full_name,
          is_active: editForm.is_active,
        })
        ElMessage.success('用户已创建')
      }
      editVisible.value = false
      return true
    } catch (e) {
      ElMessage.error((e.response && e.response.data && e.response.data.detail) || '操作失败')
      return false
    } finally {
      editLoading.value = false
    }
  }

  // ===== 重置密码 弹窗 =====
  const pwdVisible = ref(false)
  const pwdLoading = ref(false)
  const pwdTarget = ref(null)
  const pwdForm = reactive({ new_password: '', confirm: '' })

  const pwdRules = {
    new_password: [
      { required: true, message: '请输入新密码', trigger: 'blur' },
      { min: 6, message: '密码长度至少 6 位', trigger: 'blur' },
    ],
    confirm: [
      { required: true, message: '请再次输入新密码', trigger: 'blur' },
      {
        validator: (_r, v, cb) =>
          v === pwdForm.new_password ? cb() : cb(new Error('两次输入不一致')),
        trigger: 'blur',
      },
    ],
  }

  function openResetPwd(row) {
    pwdTarget.value = row
    pwdForm.new_password = ''
    pwdForm.confirm = ''
    pwdVisible.value = true
  }

  async function submitResetPwd() {
    const dlgRef = dialogRefs.pwd
    if (!dlgRef || !dlgRef.value) {
      console.error('[useUserActions] pwdDialogRef not injected by parent')
      return false
    }
    const valid = await dlgRef.value.validate().catch(() => false)
    if (!valid) return false
    pwdLoading.value = true
    try {
      await userApi.resetPassword(pwdTarget.value.id, pwdForm.new_password)
      ElMessage.success('已重置 ' + pwdTarget.value.username + ' 的密码')
      pwdVisible.value = false
      return true
    } catch (e) {
      ElMessage.error((e.response && e.response.data && e.response.data.detail) || '重置失败')
      return false
    } finally {
      pwdLoading.value = false
    }
  }

  // ===== 启用 / 禁用 / 删除（无弹窗，走 ElMessageBox 确认）=====
  async function toggleActive(row) {
    const next = !row.is_active
    const action = next ? '启用' : '禁用'
    try {
      await ElMessageBox.confirm(
        '确定要' + action + '用户「' + row.username + '」吗？',
        action + '确认',
        { type: 'warning', confirmButtonText: action, cancelButtonText: '取消' }
      )
    } catch (_) {
      return false
    }
    try {
      await userApi.update(row.id, { is_active: next })
      ElMessage.success('已' + action)
      return true
    } catch (e) {
      ElMessage.error((e.response && e.response.data && e.response.data.detail) || (action + '失败'))
      return false
    }
  }

  async function confirmDelete(row) {
    try {
      await ElMessageBox.confirm(
        '确定要删除用户「' + row.username + '」吗？该操作不可撤销。',
        '删除确认',
        {
          type: 'warning',
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          confirmButtonClass: 'el-button--danger',
        }
      )
    } catch (_) {
      return false
    }
    try {
      await userApi.delete(row.id)
      ElMessage.success('已删除')
      return true
    } catch (e) {
      ElMessage.error((e.response && e.response.data && e.response.data.detail) || '删除失败')
      return false
    }
  }

  return {
    // dialog refs 容器 (外部 Users.vue: actions.dialogRefs.edit = ref, .pwd = ref)
    dialogRefs,
    // edit
    editVisible, editLoading, editForm, editRules,
    openCreate, openEdit, submitEdit,
    // reset password
    pwdVisible, pwdLoading, pwdForm, pwdTarget, pwdRules,
    openResetPwd, submitResetPwd,
    // inline actions
    toggleActive, confirmDelete,
  }
}

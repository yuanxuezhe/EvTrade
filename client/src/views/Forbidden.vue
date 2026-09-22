<!--
  Forbidden.vue — RBAC 拒绝页 (rbac-roles-module 2026-09-21)

  用途: router 守卫发现 pageKey 不在 user.page_keys 集合时跳转至此,
  避免 return { path: '/' } 触发自我跳转死循环 (vue-router infinite redirect).
-->
<template>
  <div class="forbidden">
    <el-result icon="warning" title="无权访问" sub-title="您的角色集不含此页面权限">
      <template #extra>
        <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup>
// 占位页面 — 仅 RBAC 守卫用. P5 之后考虑做更丰富的引导 (申请权限/申请角色).
</script>

<style scoped>
.forbidden {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}
</style>
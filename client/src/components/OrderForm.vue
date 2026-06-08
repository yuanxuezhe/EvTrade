<template>
  <el-card class="order-form">
    <template #header>
      <span>交易下单</span>
    </template>

    <el-form :model="form" label-width="80px">
      <el-form-item label="股票代码">
        <el-input v-model="form.stock_code" placeholder="如 000001.SZ" />
      </el-form-item>

      <el-form-item label="方向">
        <el-radio-group v-model="form.direction">
          <el-radio label="BUY">买入</el-radio>
          <el-radio label="SELL">卖出</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="价格类型">
        <el-select v-model="form.price_type" placeholder="选择价格类型">
          <el-option label="限价" value="LIMIT" />
          <el-option label="最新价" value="LATEST" />
          <el-option label="挂单价" value="FAIR" />
        </el-select>
      </el-form-item>

      <el-form-item label="价格">
        <el-input-number v-model="form.price" :min="0" :precision="2" />
      </el-form-item>

      <el-form-item label="数量">
        <el-input-number v-model="form.volume" :min="100" :step="100" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" @click="handleSubmit">下单</el-button>
        <el-button @click="handleReset">重置</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  onSubmit: { type: Function, required: true }
})

const form = reactive({
  stock_code: '',
  direction: 'BUY',
  price_type: 'LIMIT',
  price: 0,
  volume: 100
})

function handleSubmit() {
  if (!form.stock_code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  if (form.price <= 0) {
    ElMessage.warning('请输入价格')
    return
  }
  if (form.volume <= 0) {
    ElMessage.warning('请输入数量')
    return
  }
  props.onSubmit({ ...form })
  handleReset()
}

function handleReset() {
  form.stock_code = ''
  form.direction = 'BUY'
  form.price_type = 'LIMIT'
  form.price = 0
  form.volume = 100
}
</script>

<style scoped>
.order-form {
  max-width: 400px;
}
</style>
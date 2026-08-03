# spec-delta: frontend

新增 2 个页面 + 1 个 api 客户端 + 2 个路由 + 导航菜单。

## 路由
- `/script-dev` — ScriptDev.vue (策略开发) — trader + admin
- `/script-task` — ScriptTask.vue (策略交易) — trader + admin

## ScriptDev.vue
布局:左 CodeMirror/Monaco 代码编辑器(70% 宽) + 右参数 schema 列表(30%)。

- 顶部:脚本名输入、描述、状态徽章、保存按钮、测试回测按钮
- 中部:编辑器代码(默认模板:`# === 脚本框架 ===\n# 回调: on_init/on_bar/on_tick/on_finish\n# 可用: lib.MA5(bar), lib.doorder(...)\ndef on_bar(ctx, bar):\n    ma5 = ctx.lib.MA(ctx.bars, 5)\n    if ma5 and bar.close > ma5:\n        ctx.lib.doorder(ctx.symbol, 'BUY', bar.close, 100)`)
- 右侧:参数 schema 表格(`key | type | default | min | max | step`),支持新增/删除/编辑
- 底部:保存提示,保存后显示"去回测"按钮跳 ScriptTask 并自动选择该脚本

## ScriptTask.vue
布局:顶部新建任务抽屉 + 中部任务列表(表格)+ 右侧任务详情(运行日志 + 收益曲线)。

任务表字段:
- 任务名 / 脚本名 / 标的 / 模式 / 状态 / PnL / 成交笔数 / 起止时间 / 操作(详情/停止/删除)

新建任务抽屉字段:
- 脚本(下拉)
- 标的(股票代码自动补全)
- 模式 radio:回测 / 实盘
- 参数值(根据脚本 params_schema 动态生成表单)
- 回测专属:起止日期、period
- 实盘专属:确认提示"实盘将真实下单"
- 提交按钮:"开始回测" / "启动实盘"

任务详情:
- 回测模式:展示 PnL/胜率/夏普/收益曲线图(echarts)/ 最佳参数 / 完整交易列表
- 实盘模式:展示当前持仓 + 累计 PnL + 最近 50 条信号日志 + 停止按钮

## API client: client/src/api/script_strategy.js

```js
export const scriptStrategyApi = {
  // 脚本 CRUD
  async listScripts() { ... },
  async getScript(id) { ... },
  async createScript(payload) { ... },
  async updateScript(id, patch) { ... },
  async deleteScript(id) { ... },

  // 任务
  async listTasks({ status, mode } = {}) { ... },
  async getTask(id) { ... },
  async createTask(payload) { ... },
  async stopTask(id) { ... },
  async deleteTask(id) { ... },
  async getTaskLogs(id) { ... },
}
```

## 导航菜单
在 `client/src/App.vue` 的侧边栏 `/strategy-trade` 之后追加 2 项。

## 兼容性
不复用 StrategyTrade.vue 的 components(StrategyList / StrategyConfig / RegimeEditor)。新页面独立组件树。
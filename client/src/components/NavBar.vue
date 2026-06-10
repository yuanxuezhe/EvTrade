<template>
  <el-menu mode="horizontal" :router="true">
    <el-menu-item index="/">持仓管理</el-menu-item>
    <el-menu-item index="/orders">委托查询</el-menu-item>
    <el-menu-item index="/trades">成交查询</el-menu-item>
    <el-menu-item index="/trade">交易面板</el-menu-item>
    <el-menu-item index="/asset">资金</el-menu-item>
  </el-menu>
</template>
<template>
  <div id="app">
    <NavBar />
    <router-view style="margin-top: 20px" />
  </div>
</template>

<script setup>
import NavBar from './components/NavBar.vue'
</script>

<style>
#app {
  font-family: 'Microsoft YaHei', sans-serif;
}
</style>
import { createRouter, createWebHistory } from 'vue-router'
import Position from '../views/Position.vue'
import Trade from '../views/Trade.vue'
import Asset from '../views/Asset.vue'

const routes = [
  { path: '/', name: 'Position', component: Position },
  { path: '/trade', name: 'Trade', component: Trade },
  { path: '/asset', name: 'Asset', component: Asset }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
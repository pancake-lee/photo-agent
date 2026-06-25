import { createRouter, createWebHashHistory } from 'vue-router'
import PhotoManagement from '../views/PhotoManagement.vue'

const routes = [
  { path: '/', redirect: '/photos' },
  { path: '/photos', name: 'photos', component: PhotoManagement },
  {
    path: '/golden-queries',
    name: 'golden-queries',
    component: () => import('../views/GoldenQueryManagement.vue'),
  },
  {
    path: '/cluster',
    name: 'cluster',
    component: () => import('../views/ClusterView.vue'),
  },
  {
    path: '/chat/:sessionId?',
    name: 'chat',
    component: () => import('../views/ChatView.vue'),
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router

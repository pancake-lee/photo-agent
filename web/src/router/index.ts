import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/photos' },
  {
    path: '/photos',
    name: 'photos',
    component: () => import('../views/PhotoManagement.vue'),
  },
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
    path: '/suggest',
    name: 'suggest',
    component: () => import('../views/SuggestView.vue'),
  },
  {
    path: '/chat/:sessionId?',
    name: 'chat',
    component: () => import('../views/ChatView.vue'),
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('../views/SettingsView.vue'),
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router

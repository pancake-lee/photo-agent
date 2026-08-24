import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/photos' },
  {
    path: '/photos',
    name: 'photos',
    component: () => import('../views/PhotoManagement.vue'),
  },
  {
    path: '/timelines',
    name: 'timelines',
    component: () => import('../views/TimelineManagement.vue'),
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
    path: '/post-studio',
    name: 'post-studio',
    component: () => import('../views/PostStudio.vue'),
  },
  {
    path: '/drafts',
    name: 'drafts',
    component: () => import('../views/DraftManagement.vue'),
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
  {
    path: '/import',
    name: 'import',
    component: () => import('../views/ImportWorkflow.vue'),
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router

import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'vehicles', component: () => import('@/views/VehiclesView.vue') },
    { path: '/vehicles/:id', name: 'vehicle', component: () => import('@/views/VehicleDetailView.vue') },
    { path: '/vehicles/:id/live', name: 'live', component: () => import('@/views/LiveView.vue') },
    { path: '/vehicles/:id/diagnostic', name: 'diagnostic', component: () => import('@/views/DiagnosticSessionView.vue') },
    { path: '/jobs/:id/chat', name: 'chat', component: () => import('@/views/ChatView.vue') },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') },
  ],
})

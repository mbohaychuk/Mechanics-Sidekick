import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'vehicles', component: () => import('@/views/VehiclesView.vue') },
    { path: '/vehicles/:id', name: 'vehicle', component: () => import('@/views/VehicleDetailView.vue') },
    { path: '/jobs/:id/chat', name: 'chat', component: () => import('@/views/ChatView.vue') },
  ],
})

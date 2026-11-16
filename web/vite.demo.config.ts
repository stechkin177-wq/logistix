import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
const target = 'https://logistix-api-sable.vercel.app'
export default defineConfig({
  
  plugins: [react(), tailwindcss()],
  server: { port: 5199, proxy: { '/api': { target, changeOrigin: true, secure: true, cookieDomainRewrite: '', cookiePathRewrite: '/' }, '/media': { target, changeOrigin: true } } },
})

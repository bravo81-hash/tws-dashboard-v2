import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path' // <-- ADD THIS IMPORT

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  // ADD THIS ENTIRE 'resolve' SECTION
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
import { mergeConfig } from 'vite'
import base from './vite.config'

// Dedicated SSH tunnel; connection failure must never fall back to production.
export default mergeConfig(base, {
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:18766' },
  },
})

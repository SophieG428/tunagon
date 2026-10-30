import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // Relative base so the same build works both at http://localhost:5173/ (dev)
  // and under a GitHub Pages project subpath (https://<user>.github.io/<repo>/).
  // Asset URLs (incl. the SoundFont via import.meta.env.BASE_URL) resolve relative
  // to the page, so no repo name needs to be hard-coded here.
  base: './',
  plugins: [react()],
  server: { port: 5173 },
})

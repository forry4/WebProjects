import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // Prod is a GitHub Pages USER site (repo forry4.github.io) served at the domain
  // root https://forry4.github.io/, so the base is '/'. Override with VITE_BASE only
  // if ever served under a sub-path again (e.g. a project-site repo).
  base: process.env.VITE_BASE || '/',
  plugins: [react()],
  build: {
    // The games' stylesheets are imported with `?inline` and injected by each
    // component's own <style> tag (see any game's .jsx header). They used to be JS
    // template literals, which Vite never touched. Keeping minification OFF means
    // the emitted string is the .css file VERBATIM — so moving them out of JS is a
    // provably behaviour-free change, not "probably fine because esbuild's CSS
    // minifier is usually lossless". Turn this on deliberately, with a visual
    // check, if the ~45KB is ever worth it.
    cssMinify: false,
  },
})

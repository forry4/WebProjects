import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // Prod is a GitHub Pages USER site (repo forry4.github.io) served at the domain
  // root https://forry4.github.io/, so the base is '/'. Override with VITE_BASE only
  // if ever served under a sub-path again (e.g. a project-site repo).
  base: process.env.VITE_BASE || '/',
  // Identifies THIS build. In CI it's the commit; locally it's `dev`, which switches
  // the update nudge off (nothing to compare a local build against).
  define: { __BUILD_ID__: JSON.stringify(process.env.GITHUB_SHA || 'dev') },
  plugins: [
    react(),
    {
      // Emit version.json alongside the bundle carrying the SAME id compiled into
      // it. A running tab fetches this (cache: no-store) and knows it is stale when
      // the ids differ — see shared/update-nudge.js.
      name: 'emit-build-version',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'version.json',
          source: JSON.stringify({ build: process.env.GITHUB_SHA || 'dev' }),
        })
      },
    },
  ],
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

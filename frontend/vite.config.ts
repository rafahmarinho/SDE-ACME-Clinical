import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'

function origin(url: string | undefined): string {
  if (!url) return ''
  try {
    return new URL(url).origin
  } catch {
    return ''
  }
}

/** Injects a strict Content-Security-Policy computed from the configured API and Supabase origins. */
function contentSecurityPolicy(env: Record<string, string>): Plugin {
  const api = origin(env.VITE_API_URL)
  const supabase = origin(env.VITE_SUPABASE_URL)
  const realtime = supabase.replace(/^http/, 'ws')
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    `img-src 'self' data: blob: ${supabase}`,
    "font-src 'self'",
    `connect-src 'self' ${api} ${supabase} ${realtime}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    'upgrade-insecure-requests',
  ].join('; ')
  return {
    name: 'acme-csp',
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        if (ctx.server) return html // the dev server needs inline HMR scripts
        return html.replace('<head>', `<head>\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`)
      },
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_')
  return {
    plugins: [react(), contentSecurityPolicy(env)],
    build: {
      sourcemap: false,
      target: 'es2022',
      chunkSizeWarningLimit: 1200,
    },
    server: { port: 5173, strictPort: true },
    preview: { port: 4173, strictPort: true },
  }
})

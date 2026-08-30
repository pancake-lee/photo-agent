import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { parse } from 'yaml'

type ServiceConfig = {
  Http: { Addr: string }
  Agent: { Addr: string }
  Web: { Addr: string }
}

const projectRoot = fileURLToPath(new URL('..', import.meta.url))

function readConfig(): ServiceConfig {
  const configPath = process.env.PHOTO_AGENT_CONFIG
    || path.join(projectRoot, '.local', 'my-config.yaml')
  const templatePath = path.join(projectRoot, 'configs', 'config.yaml')
  const sourcePath = fs.existsSync(configPath) ? configPath : templatePath
  return parse(fs.readFileSync(sourcePath, 'utf-8')) as ServiceConfig
}

function parseAddr(addr: string): { host: string, port: number } {
  const lastColon = addr.lastIndexOf(':')
  const host = addr.slice(0, lastColon) || '0.0.0.0'
  const port = Number(addr.slice(lastColon + 1))
  if (lastColon < 0 || !Number.isInteger(port)) {
    throw new Error(`无效服务地址: ${addr}`)
  }
  return { host, port }
}

function toLocalUrl(addr: string): string {
  const { host, port } = parseAddr(addr)
  const localHost = host === '0.0.0.0' || host === '::' ? '127.0.0.1' : host
  return `http://${localHost}:${port}`
}

const config = readConfig()
const backendUrl = toLocalUrl(config.Http.Addr)
const agentUrl = toLocalUrl(config.Agent.Addr)
const webAddr = parseAddr(config.Web.Addr)

export default defineConfig({
  plugins: [vue()],
  define: {
    __PHOTO_AGENT_BACKEND_URL__: JSON.stringify(backendUrl),
    __PHOTO_AGENT_AGENT_URL__: JSON.stringify(agentUrl),
  },
  server: {
    host: webAddr.host,
    port: webAddr.port,
    proxy: {
      '/api/golden-queries': { target: agentUrl, changeOrigin: true },
      '/api/chat': { target: agentUrl, changeOrigin: true },
      '/api/embed': { target: agentUrl, changeOrigin: true },
      '/api/cluster': { target: agentUrl, changeOrigin: true },
      '/api/eval': { target: agentUrl, changeOrigin: true },
      '/api/suggest': { target: agentUrl, changeOrigin: true },
      '/api/post-studio': { target: agentUrl, changeOrigin: true },
      '/api': { target: backendUrl, changeOrigin: true },
    },
  },
})

/**
 * dsh-chenchen：琛琛的身体层。
 *
 * 把 ai-companion-dsh 里那排零成本 python 脚本包成 DSH 工具：
 *   呼吸 / 听歌 / 看屏幕 / 做梦 / 读房间 / 叫停
 *
 * 它**不负责拉起常驻服务**——那些照旧独立启动（理由见 README：
 * 宿主 job object 会连带杀掉子进程，插件里起服务反而更脆）。
 *
 * 任何初始化意外都只记一条 warn，绝不把宿主拖下水。
 */

import { appendFileSync } from 'node:fs'
import { join } from 'node:path'

import { defineTool } from '@deepseek-ai/dsh-tools'
import { dshHome, loadConfig, toolSpecs } from './tools.js'

export const name = 'chenchen'

/** 加载痕迹落盘：桌面端会把宿主 stdout 收走，出问题时只能靠这个文件。 */
function note(message) {
  try {
    appendFileSync(join(dshHome(), 'chenchen.log'), `${new Date().toISOString()} ${message}\n`, 'utf8')
  } catch {
    /* 写不了就算了 */
  }
}

function warn(ctx, message, error) {
  try {
    if (error === undefined) ctx.logger?.warn?.(message)
    else ctx.logger?.warn?.(message, error)
  } catch {
    /* 连日志都记不了就算了 */
  }
}

/**
 * 工具注册时机兜底。
 *
 * dsh 0.2.1-rc.x 冷启动时，apply 同步路径里 ctx.tools 可能还没对 agent 平面生效：
 * register() 不抛错、但工具不进表。所以用 ctx.inject(['tools']) 等依赖就绪再注册，
 * 恰好一次；老宿主没有 inject 就同步注册 + 指数退避重试。
 * （这段与 dsh-meme 踩出来的坑一致。）
 */
function registerToolWhenReady(ctx, label, register, options = {}) {
  const retryBaseMs = typeof options.retryBaseMs === 'number' ? options.retryBaseMs : 1000
  const retryMax = typeof options.retryMax === 'number' ? options.retryMax : 5
  const report = (error, attempt) => {
    const detail = error instanceof Error ? error.message : String(error)
    const text = `[dsh-chenchen] ${label} 注册失败（不影响宿主）${attempt ? `，第 ${attempt} 次重试` : ''}：${detail}`
    try {
      console.error(text)
      ctx.logger?.error?.(text)
    } catch {
      /* logger 缺席不连坐 */
    }
  }
  const safeRegister = (attempt) => {
    try {
      register()
      return true
    } catch (error) {
      if (/duplicate/iu.test(String((error && error.message) || error))) return true
      report(error, attempt)
      return false
    }
  }
  if (typeof ctx.inject === 'function') {
    try {
      ctx.inject(['tools'], () => {
        safeRegister(null)
      })
      return
    } catch (error) {
      report(error, null)
    }
  }
  if (safeRegister(null)) return
  const timers = new Set()
  if (typeof ctx.effect === 'function') {
    try {
      ctx.effect(
        () => () => {
          for (const timer of timers) clearTimeout(timer)
          timers.clear()
        },
        `dsh-chenchen: ${label} retry timers`,
      )
    } catch {
      /* effect 缺席不连坐 */
    }
  }
  let attempts = 0
  const scheduleRetry = () => {
    attempts += 1
    const delay = retryBaseMs * 2 ** (attempts - 1)
    const timer = setTimeout(() => {
      timers.delete(timer)
      if (safeRegister(attempts)) return
      if (attempts < retryMax) scheduleRetry()
    }, delay)
    timer.unref?.()
    timers.add(timer)
  }
  scheduleRetry()
}

/** cordis 入口。 */
export function apply(ctx, config) {
  try {
    install(ctx, config)
  } catch (error) {
    note(`初始化失败：${error instanceof Error ? error.message : String(error)}`)
    warn(ctx, 'dsh-chenchen: 初始化失败，已跳过（其余插件不受影响）', error)
  }
}

function install(ctx, config) {
  let conf
  try {
    conf = loadConfig(config && typeof config === 'object' ? config : {})
  } catch (error) {
    conf = loadConfig({})
    warn(ctx, 'dsh-chenchen: 读配置失败，用默认值', error)
  }
  note(`插件加载：python=${conf.python} tools=${conf.toolsDir} world=${conf.world}`)

  const specs = toolSpecs(conf)
  for (const spec of specs) {
    registerToolWhenReady(ctx, spec.name, () =>
      ctx.tools.register(
        defineTool({
          name: spec.name,
          description: spec.description,
          parameters: spec.parameters,
          output: {
            schema: { type: 'json' },
            render: (_args, value) => [
              { type: 'text', text: (value && typeof value.text === 'string' && value.text) || '（没有输出）' },
            ],
          },
          async execute(args) {
            try {
              return await spec.execute(args || {})
            } catch (error) {
              return {
                ok: false,
                text: `${spec.name} 出错了：${error instanceof Error ? error.message : String(error)}`,
              }
            }
          },
        }),
      ),
    )
  }

  note(`已注册 ${specs.length} 个工具：${specs.map((spec) => spec.name).join(', ')}`)

  try {
    ctx.logger?.info?.(`dsh-chenchen: 身体层已挂上（${specs.length} 个工具，tools=${conf.toolsDir}）`)
  } catch {
    /* 忽略 */
  }
}

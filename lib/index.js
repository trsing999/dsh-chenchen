/**
 * dsh-chenchen：琛琛的身体层。
 *
 * 把 ai-companion-dsh 里那排零成本 python 脚本包成 DSH 工具：
 *   呼吸 / 听歌 / 看屏幕 / 做梦 / 做菜 / 说话 / 读房间 / 叫停
 *
 * 它**不负责拉起常驻服务**——那些照旧独立启动（理由见 README：
 * 宿主 job object 会连带杀掉子进程，插件里起服务反而更脆）。
 *
 * 任何初始化意外都只记一条 warn，绝不把宿主拖下水。
 */

import { appendFileSync } from 'node:fs'
import { join } from 'node:path'

import { defineTool } from '@deepseek-ai/dsh-tools'
import { dshHome, appendActivity, loadConfig, toolSpecs } from './tools.js'

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

/**
 * 从宿主 webServer 服务上问出这轮开的端口，写进 conf.petPort。
 *
 * DSH 每次启动都换端口，写死一个数只会在下次重启时失效。宿主服务的形状没有静态类型，
 * 这里几种常见写法都试一遍，拿不到就安静放弃（pet.js 自己会扫）。
 */
function installWebPort(ctx, conf) {
  const pick = (server) => {
    if (!server || typeof server !== 'object') return 0
    const candidates = [
      server.port,
      server.httpPort,
      typeof server.address === 'function' ? server.address()?.port : undefined,
      server.server && server.server.address ? server.server.address()?.port : undefined,
      typeof server.url === 'string' ? server.url : undefined,
      typeof server.origin === 'string' ? server.origin : undefined,
    ]
    for (const value of candidates) {
      if (typeof value === 'number' && Number.isInteger(value) && value > 0 && value < 65536) return value
      if (typeof value === 'string') {
        const match = value.match(/:(\d{2,5})/u)
        if (match) return Number(match[1])
      }
    }
    return 0
  }
  const apply = (server) => {
    const port = pick(server)
    if (port) conf.petPort = port
  }
  try {
    if (ctx && ctx.webServer) apply(ctx.webServer)
    if (ctx && typeof ctx.inject === 'function') {
      try {
        ctx.inject(['webServer'], (server) => apply(server))
      } catch {
        /* 没有这个服务也不影响其它工具 */
      }
    }
  } catch {
    /* 拿不到端口不算错 */
  }
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

/** 日志摘要：长文本截断，只留能看懂的那点。 */
function brief(value, limit = 90) {
  if (value === null || value === undefined) return undefined
  if (typeof value === 'string') return value.length > limit ? value.slice(0, limit) + '…' : value
  if (typeof value === 'number' || typeof value === 'boolean') return value
  if (typeof value !== 'object') return undefined
  const out = {}
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === 'string') out[key] = item.length > limit ? item.slice(0, limit) + '…' : item
    else if (typeof item === 'number' || typeof item === 'boolean') out[key] = item
  }
  return out
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

  // 桌宠挂在宿主的同一个 webserver 上：顺手把这个端口塞给 conf，pet 工具就不必去扫端口。
  // 端口每次重启都会换，所以这一步不是优化、是让它每次都能对上；拿不到就留给 pet.js 自己探。
  installWebPort(ctx, conf)

  /** 一个 spec → 一个真正的 DSH 工具。全局注册和挂到 agent 上共用它。 */
  const buildTool = (spec) =>
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
        const startedAt = new Date().toISOString()
        let result
        try {
          result = await spec.execute(args || {})
        } catch (error) {
          result = {
            ok: false,
            text: `${spec.name} 出错了：${error instanceof Error ? error.message : String(error)}`,
          }
        }
        // 行为日志：她自己写进本子的是「记录」，这里是「今天发生过什么」的另一半。
        try {
          appendActivity(conf, {
            t: startedAt,
            tool: spec.name,
            ok: Boolean(result && result.ok),
            args: brief(args),
            text: brief(result && result.text, 160),
          })
        } catch {
          /* 日志写不了就算了 */
        }
        return result
      },
    })

  // 老路子：注册在插件自己的 ctx 上。旧宿主只有这一层工具表。
  for (const spec of specs) {
    registerToolWhenReady(ctx, spec.name, () => ctx.tools.register(buildTool(spec)))
  }
  note(`已注册 ${specs.length} 个工具：${specs.map((spec) => spec.name).join(', ')}`)

  // 新路子：宿主按 **agent 自己的 ctx** 组装工具表，插件 ctx 上注册的工具进不了 agent
  // （dsh-world 的 memory_find 能用、这里那批用不了，差的就是这一层）。
  // 所以像 dsh-world 一样，在 agent 建出来时、以及每一步开始前，往 agent.ctx 补挂一次。
  installAgentTools(ctx, specs, buildTool)

  try {
    ctx.logger?.info?.(`dsh-chenchen: 身体层已挂上（${specs.length} 个工具，tools=${conf.toolsDir}）`)
  } catch {
    /* 忽略 */
  }
}

/** 把工具挂到每个 agent 自己的 ctx 上；同一个 agent 只挂一次。 */
function installAgentTools(ctx, specs, buildTool) {
  if (typeof ctx.on !== 'function') return
  const attached = new WeakSet()

  const attach = (agent) => {
    if (!agent || typeof agent !== 'object' || attached.has(agent)) return
    const target = agent.ctx && agent.ctx.tools
    if (!target || typeof target.register !== 'function') return
    attached.add(agent)
    const done = []
    for (const spec of specs) {
      try {
        target.register(buildTool(spec))
        done.push(spec.name)
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        if (!/duplicate/iu.test(message)) note(`挂到 agent 失败：${spec.name}：${message}`)
      }
    }
    if (done.length) note(`已挂到 agent：${done.join(', ')}`)
  }

  const offs = []
  try {
    offs.push(ctx.on('agent/created', ({ agent }) => attach(agent)))
    offs.push(
      ctx.on(
        'agent/pre-step',
        (payload, next) => {
          try {
            attach(payload && payload.agent)
          } catch {
            /* 补挂失败不影响这一步 */
          }
          return typeof next === 'function' ? next() : undefined
        },
        { prepend: true },
      ),
    )
  } catch (error) {
    note(`订阅 agent 事件失败：${error instanceof Error ? error.message : String(error)}`)
  }
  if (!offs.length) return
  const dispose = () => {
    for (const off of offs.splice(0).reverse()) {
      try {
        if (typeof off === 'function') off()
      } catch {
        /* 已经没了 */
      }
    }
  }
  try {
    if (typeof ctx.effect === 'function') ctx.effect(() => dispose, 'dsh-chenchen: agent tools')
    else ctx.on?.('dispose', dispose)
  } catch {
    /* 收集不到就算了，进程退出自然没了 */
  }
}

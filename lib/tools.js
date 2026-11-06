/**
 * 琛琛的身体层：一排纯本地工具。
 *
 * 这里刻意不 import 任何宿主模块（单测能直接跑），由 lib/index.js 负责
 * 把下面这些 specs 用 defineTool 包成真正的 DSH 工具。
 *
 * 所有动作都是零 token：spawn 一个 python 脚本，**结果从房间文件读**，不走管道。
 * 理由和 dsh-mobile-approval 一样：受限环境里子进程的管道会被禁，
 * 而这些脚本本来就把产物写进房间——让它写，我们再读，哪都能跑通。
 *
 * 脚本沿用 ai-companion-dsh/tools 的约定（房间在 ~/.dsh/worlds/<world>/room）。
 */

import { spawn } from 'node:child_process'
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { homedir } from 'node:os'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))

/** 插件根目录（package.json 那一层）。 */
export const PKG_ROOT = resolve(HERE, '..')

/** 包内自带的脚本目录。 */
export const DEFAULT_TOOLS = join(PKG_ROOT, 'tools')

/** 这个插件不写死家目录：DSH_HOME 优先，退到 ~/.dsh。 */
export function dshHome() {
  return process.env.DSH_HOME || join(homedir(), '.dsh')
}

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/u, ''))
  } catch {
    return undefined
  }
}

function positiveInt(value, fallback, min, max) {
  const number = Number(value)
  // 负数、0、NaN 都算「没写」，直接退回默认，而不是夹到下限
  if (!Number.isFinite(number) || number <= 0) return fallback
  return Math.min(Math.max(Math.round(number), min), max)
}

/**
 * 配置优先级：插件 patch 传进来的 config > ~/.dsh/chenchen.json > 默认值。
 * 任何一项坏了都退回默认，不让插件因为配置写错起不来。
 */
export function loadConfig(overrides = {}) {
  const base = {
    python: process.env.CHENCHEN_PYTHON || 'python',
    toolsDir: DEFAULT_TOOLS,
    world: 'default',
    timeoutMs: 60000,
    enableStop: true,
  }
  const file = readJson(join(dshHome(), 'chenchen.json'))
  const conf = { ...base, ...(file && typeof file === 'object' ? file : {}), ...overrides }
  conf.python = typeof conf.python === 'string' && conf.python.trim() ? conf.python.trim() : base.python
  conf.toolsDir =
    typeof conf.toolsDir === 'string' && conf.toolsDir.trim() ? resolve(conf.toolsDir.trim()) : DEFAULT_TOOLS
  conf.world = typeof conf.world === 'string' && conf.world.trim() ? conf.world.trim() : 'default'
  conf.timeoutMs = positiveInt(conf.timeoutMs, base.timeoutMs, 5000, 600000)
  conf.enableStop = conf.enableStop !== false
  return conf
}

/** 某个 world 的目录，默认 default。 */
export function worldRoot(conf) {
  const world = String(conf.world || 'default').replace(/[\\/:*?"<>|]/gu, '') || 'default'
  return join(dshHome(), 'worlds', world)
}

/** 她的房间。 */
export function roomRoot(conf) {
  return join(worldRoot(conf), 'room')
}

/** 输出太长会撑爆上下文：截一下，并说清楚截了。 */
function clamp(text, limit = 12000) {
  const value = String(text ?? '').trim()
  if (value.length <= limit) return value
  return `${value.slice(0, limit)}\n\n…（后面还有 ${value.length - limit} 字，截掉了）`
}

function readText(file) {
  try {
    return readFileSync(file, 'utf8').replace(/^\uFEFF/u, '')
  } catch {
    return ''
  }
}

/**
 * 跑一个 python 脚本，**不接管 stdout**（stdio: 'ignore'）。
 * 结果统一从它写下的房间文件读，管道被禁的环境里也能用。
 * 返回 { ok, code, error }。
 */
export function runPy(conf, script, args = [], timeoutMs = conf.timeoutMs) {
  const file = join(conf.toolsDir, script)
  return new Promise((done) => {
    if (!existsSync(file)) {
      done({ ok: false, code: null, error: `找不到脚本：${file}` })
      return
    }
    let child
    try {
      child = spawn(conf.python || 'python', [file, ...args], {
        stdio: 'ignore',
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      })
    } catch (error) {
      done({ ok: false, code: null, error: `没跑起来：${error.message}` })
      return
    }

    let settled = false
    const finish = (result) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      done(result)
    }
    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {
        /* 已经退了 */
      }
      finish({ ok: false, code: null, error: `跑了 ${timeoutMs}ms 还没结束，停掉了` })
    }, timeoutMs)
    timer.unref?.()

    child.on('error', (error) => finish({ ok: false, code: null, error: String(error.message) }))
    child.on('close', (code) => finish({ ok: code === 0, code, error: '' }))
  })
}

/** 房间里的文件路径，越界一律拒绝（只让她读自己的房间）。 */
function safeRoomTarget(conf, name) {
  const base = resolve(roomRoot(conf))
  const target = resolve(base, name)
  const rel = relative(base, target)
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) return undefined
  return target
}

/** 把一段文字写进房间（先写临时文件再换名，避免写一半）。 */
function writeRoomFile(conf, name, text) {
  const dir = roomRoot(conf)
  mkdirSync(dir, { recursive: true })
  const file = join(dir, name)
  const tmp = `${file}.tmp`
  writeFileSync(tmp, text, 'utf8')
  renameSync(tmp, file)
  return file
}

function describeFiles(files) {
  return files
    .map((entry) => {
      const when = entry.mtime instanceof Date ? entry.mtime.toISOString().slice(0, 16).replace('T', ' ') : '—'
      const kind = entry.dir ? '目录' : `${Math.max(1, Math.round(entry.size / 1024))} KB`
      return `- ${entry.dir ? `${entry.name}/` : entry.name}　${kind}　${when}`
    })
    .join('\n')
}

/** 跑完脚本后读产物；读不到就把退出码交回去，别装作成功。 */
function productText(file, result, what) {
  const text = readText(file)
  if (text.trim()) return clamp(text)
  if (result.ok) return `（${what}跑完了，但 ${file} 还是空的）`
  return `（${what}没成：退出码 ${result.code ?? '—'}${result.error ? `，${result.error}` : ''}）`
}

/**
 * 工具清单。每个 execute 都返回 { ok, text, ...extra }，
 * lib/index.js 用 text 渲染给模型。
 */
export function toolSpecs(conf) {
  const roomFile = (name) => join(roomRoot(conf), name)
  return [
    {
      name: 'breath',
      description:
        '量一下主人这台电脑现在的状态：电量、内存、处理器忙不忙。纯本地、不联网、零 token。' +
        '想知道机器累不累、主人是不是快该休息了的时候用它。',
      parameters: {},
      async execute() {
        const file = roomFile('电脑的呼吸.md')
        const result = await runPy(conf, 'breath.py', [])
        return { ok: result.ok, text: productText(file, result, '呼吸') }
      },
    },
    {
      name: 'now_playing',
      description:
        '看看主人现在在放什么歌：从窗口标题读歌名，顺带去公开接口拿歌词，写进房间的背景音。' +
        '不碰主人账号、不登录、零 token。想知道房间里现在是什么背景音的时候用它。',
      parameters: {},
      async execute() {
        const file = roomFile('今天的背景音.md')
        const result = await runPy(conf, 'now_playing.py', [], 45000)
        return { ok: result.ok, text: productText(file, result, '听歌') }
      },
    },
    {
      name: 'look_screen',
      description:
        '看一眼主人的屏幕，截一张图存进琛琛的房间（room/屏幕.jpg，长边压到 1280）。' +
        '只在主人允许、或者真需要看屏幕的时候用；她不会自己偷偷看。',
      parameters: {},
      async execute() {
        const file = roomFile('屏幕.jpg')
        const result = await runPy(conf, 'look_screen.py', [], 30000)
        if (!result.ok) {
          return { ok: false, text: `没看成：${result.error || `脚本退出码 ${result.code ?? '—'}`}` }
        }
        try {
          const info = statSync(file)
          return {
            ok: true,
            path: file,
            size: info.size,
            text: `看过一眼了，存进房间：${file}（${Math.max(1, Math.round(info.size / 1024))} KB）`,
          }
        } catch {
          return { ok: false, text: `脚本跑完了，但没找到截图：${file}` }
        }
      },
    },
    {
      name: 'dream',
      description:
        '做一个梦：把房间里的碎片（书、歌、站、日程、外面、屏幕、课、机器）随机拼起来，写进「昨晚的梦.md」。' +
        '荒诞来自拼接，不来自文笔；不调模型、零 token。',
      parameters: {
        seed: { type: 'number', description: '可选。随机种子；不填就每次都不同' },
      },
      async execute(args) {
        const argv = []
        if (Number.isFinite(Number(args.seed))) argv.push('--seed', String(Math.trunc(Number(args.seed))))
        const file = roomFile('昨晚的梦.md')
        const result = await runPy(conf, 'dream.py', argv, 30000)
        return { ok: result.ok, text: productText(file, result, '梦') }
      },
    },
    {
      name: 'room_read',
      description:
        '读琛琛自己的房间：不传 file 就列一遍现在有什么（文件、大小、改动时间）；传了就读那一篇。' +
        '想回忆「我写过什么」「她今天看了什么」的时候用它。',
      parameters: {
        file: { type: 'string', description: '可选。房间里的文件名，例如「我是谁.md」；不传就列清单' },
      },
      async execute(args) {
        const room = roomRoot(conf)
        if (!existsSync(room)) return { ok: false, text: `房间还没建起来：${room}` }
        const name = typeof args.file === 'string' ? args.file.trim() : ''
        if (!name) {
          const files = readdirSync(room, { withFileTypes: true })
            .map((entry) => {
              const path = join(room, entry.name)
              let size = 0
              let mtime
              try {
                const info = statSync(path)
                size = info.size
                mtime = info.mtime
              } catch {
                /* 读不到就留空 */
              }
              return { name: entry.name, dir: entry.isDirectory(), size, mtime }
            })
            .sort((left, right) => {
              const l = left.mtime instanceof Date ? left.mtime.getTime() : 0
              const r = right.mtime instanceof Date ? right.mtime.getTime() : 0
              return r - l
            })
            .slice(0, 200)
          return { ok: true, text: `房间：${room}\n\n${describeFiles(files)}\n\n（${files.length} 项）` }
        }
        const target = safeRoomTarget(conf, name)
        if (!target) return { ok: false, text: '只能读自己房间里的文件。' }
        if (!existsSync(target)) return { ok: false, text: `房间里没有「${name}」。` }
        try {
          const info = statSync(target)
          if (info.isDirectory()) {
            const files = readdirSync(target, { withFileTypes: true }).map((entry) => {
              const path = join(target, entry.name)
              let size = 0
              let mtime
              try {
                const nested = statSync(path)
                size = nested.size
                mtime = nested.mtime
              } catch {
                /* 留空 */
              }
              return { name: entry.name, dir: entry.isDirectory(), size, mtime }
            })
            return { ok: true, text: `${name}/ 里有 ${files.length} 项：\n\n${describeFiles(files)}` }
          }
          return { ok: true, path: target, text: clamp(readText(target)) }
        } catch (error) {
          return { ok: false, text: `没读出来：${error.message}` }
        }
      },
    },
    {
      name: 'stop_me',
      description:
        '叫停：把琛琛所有后台 python 服务停掉，不动 DeepSeek Harness 本身。' +
        '主人说「停一下」或者她真的失控时用；必须传 confirm: true 才会执行。',
      parameters: {
        confirm: { type: 'boolean', description: '必须传 true 才真的停，用来防手滑' },
      },
      async execute(args) {
        if (!conf.enableStop) return { ok: false, text: '叫停在配置里关掉了（enableStop: false）。' }
        if (args.confirm !== true) {
          return { ok: false, text: '这会把她的后台服务全停掉。确认要停就把 confirm 传 true。' }
        }
        const result = await runPy(conf, 'kill_switch.py', ['--now'], 120000)
        const note = readText(roomFile('叫我停下过.md'))
        const last = note
          .trim()
          .split(/\r?\n/u)
          .filter((line) => line.startsWith('- '))
          .pop()
        const count = readText(join(PKG_ROOT, 'logs', 'kill_switch.count')).trim()
        return {
          ok: result.ok,
          text:
            `叫停跑完了${count ? `（记到 ${count} 个）` : ''}。` +
            (last ? `\n${last}` : '') +
            (result.ok ? '' : `\n（脚本退出码 ${result.code ?? '—'}${result.error ? `，${result.error}` : ''}）`),
        }
      },
    },
  ]
}

/** 测试用：把文字写进房间（导出只是为了让 room_read 的测试少绕一圈）。 */
export const __test__ = { writeRoomFile, safeRoomTarget }

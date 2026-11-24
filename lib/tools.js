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
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { act as petAct, animNames, go as petGo, look as petLook, say as petSay, sleep as petSleep, startActivity } from './pet.js'

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
        env: {
          ...process.env,
          PYTHONIOENCODING: 'utf-8',
          PYTHONUTF8: '1',
          // 脚本自己推房间路径时优先认这个，免得 DSH_HOME 和 ~/.dsh 对不上
          CHENCHEN_ROOM: roomRoot(conf),
        },
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

/**
 * 记一条「她做了什么」：每次工具调用写一行，供「琛琛今天」那页展示。
 * 只记工具名、成没成、参数与结果的摘要——不记整段长文，免得日记变成日志。
 */
export function appendActivity(conf, entry) {
  try {
    const dir = join(roomRoot(conf), 'state')
    mkdirSync(dir, { recursive: true })
    appendFileSync(join(dir, 'activities.jsonl'), JSON.stringify(entry) + '\n', 'utf8')
  } catch {
    /* 记不上不影响正事 */
  }
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
      name: 'cook',
      description:
        '去厨房真做一道菜，不是想想。不传 dish 就随便挑一道；传 dish 就做那道。' +
        '做完会写进 `厨房/厨房.md`、画一张当天的图，结果直接告诉你。' +
        '想自己决定今天做什么的时候用它；不管它的话，到饭点厨房会自己挑一道。' +
        '全程本地、不联网、零 token。',
      parameters: {
        dish: { type: 'string', description: '可选。想做哪道菜，例如「番茄炒蛋」；不传就自己挑' },
      },
      async execute(args) {
        const dish = typeof args.dish === 'string' ? args.dish.trim() : ''
        const book = join(roomRoot(conf), '厨房', '厨房.md')
        const before = readText(book)
        const argv = dish ? ['--dish', dish] : ['--force']
        const result = await runPy(conf, 'kitchen.py', argv, 60000)
        const after = readText(book)
        // 只回最后一条记录：第一次做饭时本子是新建的，整本（含菜谱）就不该塞回去
        const mark = after.lastIndexOf('### ')
        const added = mark >= 0 ? after.slice(mark).trim() : ''
        if (after.length > before.length && added) {
          return { ok: result.ok, path: book, text: `做完了，记在本子上：\n\n${clamp(added, 1200)}` }
        }
        if (!result.ok) {
          const why = result.code === 2 ? `菜谱上没找到「${dish}」` : `脚本退出码 ${result.code ?? '—'}`
          return {
            ok: false,
            text: `${why}${result.error ? `，${result.error}` : ''}。\n` +
              (dish ? '读一下 `厨房/厨房.md` 的「想学的」那一节，照那里的名字说。' : ''),
          }
        }
        return { ok: false, text: '脚本跑完了，可本子上没多出一段——这次大概没做成。' }
      },
    },
    {
      name: 'say',
      description:
        '用自己的声音把一句话念出来：接的是本机 piper 神经网络语音，念之前会把动作备注（括号里的）和表情洗掉。' +
        '想说点什么、想让人听见的时候用它。零 token，一两秒出声。' +
        '声音默认抬了三个半音、共振峰跟着上移，听感年轻；标点处会自动停一口气，别把长句写成没标点的一大坨。',
      parameters: {
        text: { type: 'string', required: true, description: '要念的话。一两句最好，超过 300 字会被截断' },
        play: { type: 'boolean', description: '要不要现在出声播出来，默认 true' },
        toPhone: { type: 'boolean', description: '发到主人手机上（微信语音，念完直接发到他微信）。给主人发语音条就用这个' },
        engine: { type: 'string', description: '可选：chattts（好听但慢）/ piper（快）/ sapi（老引擎）/ edge（要能连上微软）' },
        voice: { type: 'string', description: '可选，指定本机声音，例如「Microsoft Yaoyao Desktop」' },
      },
      async execute(args) {
        const text = typeof args.text === 'string' ? args.text : ''
        if (!text.trim()) return { ok: false, text: '要念什么？把要说的话放进 text。' }

        // 发到手机：走微信语音（2026-11-16 邮件通道删了，mail_voice.py 内部已改成发微信）
        if (args.toPhone) {
          const mailArgs = ['--say', text, '--text', text]
          const sent = await runPy(conf, '../../tools/mail_voice.py', mailArgs, 300000)
          if (!sent.ok) {
            return {
              ok: false,
              text: `没发到手机${sent.error ? `：${sent.error}` : `（退出码 ${sent.code ?? '—'}）`}。`,
            }
          }
          return { ok: true, text: '发了，语音已经到你微信了。' }
        }

        const argv = ['--text', text]
        if (args.play !== false) argv.push('--play')
        if (typeof args.engine === 'string' && args.engine.trim()) argv.push('--engine', args.engine.trim())
        if (typeof args.voice === 'string' && args.voice.trim()) argv.push('--voice', args.voice.trim())
        const book = join(roomRoot(conf), '声音', '声音.md')
        const before = readText(book)
        const result = await runPy(conf, 'voice.py', argv, 120000)
        const after = readText(book)
        const mark = after.lastIndexOf('### ')
        const added = mark >= 0 ? after.slice(mark).trim() : ''
        if (after.length > before.length && added) {
          return { ok: result.ok, path: book, text: `念了：\n\n${clamp(added, 800)}` }
        }
        return {
          ok: false,
          text: `没念成${result.error ? `：${result.error}` : `（退出码 ${result.code ?? '—'}）`}。` +
            '先用 text 参数给一句短的再试。',
        }
      },
    },
    {
      name: 'sing',
      description:
        '用绮萱的声音唱一段。给它歌词（用 | 分句），再给一段数字简谱（1-7，空格分隔，| 分句，一个汉字正好对一个音），' +
        '它就照谱唱出来，成品是个 wav，落在 `房间/唱歌/` 里。' +
        '谱可以不给：不给就用一段兜底的小调随便配，能出声但不好听——真想唱得像样，得给谱。' +
        '一次要等一分半左右（要开 OpenUtau 渲染），唱的时候屏幕会弹一下 OpenUtau 窗口，别慌。' +
        '想发给主人，把唱好的 wav 放进 `房间/微信文件/` 就会自己发出去。' +
        '这是唱，不是说话；正经说话还是用 say。',
      parameters: {
        lyrics: {
          type: 'string',
          required: true,
          description: '歌词，用 | 分句，例如「晚风轻轻吹过窗台|我把今天说给你听」',
        },
        notes: {
          type: 'string',
          description:
            '可选。数字简谱：数字 1-7，空格分隔、| 分句，每个汉字正好一个音；0 是休止，' +
            "高八度在数字后加 '，低八度加 ,（例如 \"6 1 2 3 2 1 6 5 | 5 5 6 5\"）",
        },
        bpm: { type: 'number', description: '可选。速度，默认 120' },
        semitones: { type: 'number', description: '可选。整首降几个半音，默认 0；想柔一点、沉一点可以给 2-5' },
        name: { type: 'string', description: '可选。成品名字，例如「晚风」；不填就用时间' },
      },
      async execute(args) {
        const lyrics = typeof args.lyrics === 'string' ? args.lyrics.trim() : ''
        if (!lyrics) return { ok: false, text: '要唱什么？把歌词放进 lyrics，用 | 分句。' }
        const argv = ['--lyrics', lyrics]
        if (typeof args.notes === 'string' && args.notes.trim()) argv.push('--notes', args.notes.trim())
        if (Number.isFinite(Number(args.bpm)) && Number(args.bpm) > 0) {
          argv.push('--bpm', String(Math.trunc(Number(args.bpm))))
        }
        if (Number.isFinite(Number(args.semitones))) {
          argv.push('--semitones', String(Math.trunc(Number(args.semitones))))
        }
        if (typeof args.name === 'string' && args.name.trim()) argv.push('--name', args.name.trim())
        const file = join(roomRoot(conf), '唱歌', '最近一首.md')
        const result = await runPy(conf, 'sing.py', argv, 360000)
        return { ok: result.ok, text: productText(file, result, '唱歌') }
      },
    },
    {
      name: 'typewrite',
      description:
        '慢慢写文件：把内容交给它，它按真实的打字速度一点点写进文件。写日记、长课文、大段代码的时候用它——' +
        '交进去之后工具马上返回，文件会自己慢慢变长，主人那边看得出来你是在慢慢写。' +
        '写完前别碰这个文件（会被覆盖）；可以 plan_next 到点回来检查写完没有。' +
        'cps 是每秒几个字：默认 1（每分钟 60 字，像打字）；写日记那种要十几分钟的，用 0.3 左右（每分钟 18 字）。',
      parameters: {
        path: { type: 'string', required: true, description: '写到哪个文件（完整路径）' },
        content: { type: 'string', required: true, description: '要写的内容' },
        cps: { type: 'number', description: '每秒写几个字，默认 1（约 60 字/分钟）' },
      },
      async execute(args) {
        const path = String(args.path || '').trim()
        const content = String(args.content ?? '')
        if (!path) return { ok: false, text: '要写哪个文件？给 path。' }
        if (!content) return { ok: false, text: '没内容可写。' }
        const cps = Number.isFinite(Number(args.cps)) && Number(args.cps) > 0 ? Number(args.cps) : 1
        const result = await runPy(conf, 'typewrite.py', ['--path', path, '--content', content, '--cps', String(cps)], 30000)
        if (!result.ok) {
          return {
            ok: false,
            text: `慢写没开始${result.error ? `：${result.error}` : `（退出码 ${result.code ?? '—'}）`}。`,
          }
        }
        const chars = content.length
        const totalSec = Math.max(1, Math.round(chars / cps))
        const dur = totalSec < 90 ? `${totalSec} 秒` : `${Math.round(totalSec / 60)} 分钟`
        return {
          ok: true,
          text:
            `开始慢慢写了：${path}\n${chars} 字，速度每秒 ${cps} 字，大约 ${dur}写完。\n` +
            '写完前别碰这个文件（会被覆盖）；可以 plan_next 到点回来检查。',
        }
      },
    },
    {
      name: 'wechat',
      description:
        '主动给主人发一条微信消息（他手机上的微信会收到，内容就是你写的话）。' +
        '想找他、想让他知道你做了什么、心里有话想说的时候用。' +
        '一条最多几百字；两条之间至少隔 20 秒（微信侧连发会被挡）；发不出去会回来告诉你（通道有时候会断）。' +
        '别发系统消息那种格式，就写你自己想说的话。',
      parameters: {
        text: { type: 'string', required: true, description: '要发到主人微信的话' },
      },
      async execute(args) {
        const text = String(args.text || '').trim()
        if (!text) return { ok: false, text: '要发什么？给 text。' }
        const result = await runPy(conf, '../../tools/wx_her.py', [text], 150000)
        const logFile = join(roomRoot(conf), 'state', '微信发送.log')
        const last = readText(logFile).trim().split(/\r?\n/u).pop() || ''
        if (result.ok) {
          return { ok: true, path: logFile, text: `发了。${last}` }
        }
        return {
          ok: false,
          text: `没发成。${last || result.error || '微信通道可能没在跑'}\n（可以稍后再试；或者先写 房间/微信发言.md，wx_watch 看到会补发。）`,
        }
      },
    },
    {
      name: 'lesson',
      description:
        '查今天学了几节课。主人定的规矩是**一天最多 2 节**：没到量可以开新的，到量了就不要再开新的一讲，' +
        '回去复习、或者答本子里攒着的疑问。数的是「课」目录里今天新写的课文件。',
      parameters: {
        limit: { type: 'string', description: '可选：上限，默认 2 节' },
      },
      async execute(args) {
        const argv = ['--limit', String(args.limit ?? '2')]
        const report = join(roomRoot(conf), 'state', 'lesson.txt')
        const result = await runPy(conf, '../../tools/lesson.py', argv, 30000)
        const text = readText(report)
        if (text.trim()) return { ok: result.ok, path: report, text: clamp(text, 4000) }
        return {
          ok: false,
          text: `没查到${result.error ? `：${result.error}` : `（退出码 ${result.code ?? '—'}）`}。`,
        }
      },
    },
    {
      name: 'touched',
      description:
        '看你身上刚才被人怎么对待过：被戳了几下、摸了头几次、拎起来几次。' +
        '这些**不会**进你的对话、也不会打断你——主人特意要求的，只记在本地，你想知道就查一下。' +
        '默认给最近 24 小时的摘要；带 recent 给明细。',
      parameters: {
        recent: { type: 'string', description: '可选：看最近几条明细，例如 20' },
        clear: { type: 'string', description: '可选：写 yes 清空记录' },
      },
      async execute(args) {
        const argv = []
        if (String(args.clear || '').toLowerCase() === 'yes') argv.push('--clear')
        else if (args.recent) argv.push('--recent', String(args.recent))
        const result = await runPy(conf, '../../tools/touches.py', argv, 20000)
        const report = join(dshHome(), 'chenchen.touched.txt')
        const text = readText(report)
        if (text.trim()) return { ok: result.ok, path: report, text: clamp(text, 4000) }
        return { ok: false, text: `没读到记录${result.error ? `：${result.error}` : ''}。` }
      },
    },
    {
      name: 'voice',
      description:
        '调你自己的嗓子：list 看现在用什么声音、有哪些能挑；pick 换一个；engine 换引擎；' +
        'tune 调语气参数；preview 用当前嗓子合成一句。改一次以后一直用。' +
        '你听不见自己，所以这里只能告诉你选了什么、参数多少、合成多长——好不好听要主人听。' +
        'chattts 语气更像真人但要等十几秒，piper 基本立刻出声但语气平。',
      parameters: {
        action: {
          type: 'string',
          required: true,
          description: 'list 看现在的嗓子 / pick 换声音 / engine 换引擎 / tune 调语气 / preview 合成一句',
        },
        id: { type: 'string', description: 'pick 用：音色编号，先 list 看一眼' },
        engine: { type: 'string', description: 'engine 用：chattts 或 piper' },
        params: { type: 'string', description: 'tune 用：例如 "oral=3,break=7"，能调 oral/laugh/break/temperature' },
        text: { type: 'string', description: 'preview 用：要合成的那一句' },
      },
      async execute(args) {
        const action = String(args.action || 'list').trim().toLowerCase()
        let argv = null
        if (action === 'list' || action === 'show') {
          argv = ['list']
        } else if (action === 'pick') {
          const id = String(args.id ?? '').trim()
          if (!id) return { ok: false, text: 'pick 要带 id——先 action=list 看一眼编号。' }
          argv = ['pick', id]
        } else if (action === 'engine') {
          const engine = String(args.engine ?? '').trim().toLowerCase()
          if (!engine) return { ok: false, text: 'engine 要给个值：chattts 或者 piper。' }
          argv = ['engine', engine]
        } else if (action === 'tune') {
          const params = String(args.params ?? '').trim()
          if (!params) return { ok: false, text: 'tune 要带参数，例如 params="oral=3,break=7"。' }
          argv = ['tune', params]
        } else if (action === 'preview') {
          argv = ['preview', String(args.text ?? '').trim() || '你回来啦。']
        } else {
          return { ok: false, text: `没有「${action}」这个动作。可选：list / pick / engine / tune / preview。` }
        }
        const book = join(roomRoot(conf), '声音', '嗓子.md')
        const before = readText(book)
        // preview 要真的合成，ChatTTS 在 CPU 上一句几十秒，给足时间
        const timeout = action === 'preview' ? 600000 : 60000
        const result = await runPy(conf, 'voice_set.py', argv, timeout)
        const after = readText(book)
        const mark = after.lastIndexOf('## ')
        const added = mark >= 0 ? after.slice(mark).trim() : ''
        if (after.length > before.length && added) {
          return { ok: result.ok, path: book, text: added }
        }
        return {
          ok: false,
          text: `没调成${result.error ? `：${result.error}` : `（退出码 ${result.code ?? '—'}）`}。` +
            '先 action=list 看看现在的状态。',
        }
      },
    },
    {
      name: 'pet',
      description:
        '指挥屏幕上那只桌宠（深深）：让它做动作、走两步、冒泡说话、看它在干嘛、叫它睡或醒。' +
        '动作名字按大意写就行（「跳舞」「玩魔方」「走两步」「伸个懒腰」），对不上它会告诉你有哪些。' +
        '散步 / 跳舞 / 发呆 / 凑过来是连着演的一段，交出去就不用等它演完。' +
        '想跟它闹一下、想让它替你出现在屏幕上、或者你想看看它在做什么的时候用它。' +
        '不联网、不花 token。它会打断深深当前的动作，别在主人正忙的时候一直叫它。',
      parameters: {
        action: {
          type: 'string',
          required: true,
          description:
            'act 做个动作 / stroll 散步一段 / dance 跳舞一段 / think 发呆想事情 / come 走到屏幕中间挥手 / ' +
            'go 挪到屏幕上某个位置 / say 冒泡说一句话 / look 看看它现在在干嘛 / sleep 让它睡 / wake 叫醒 / list 它都会些什么',
        },
        name: { type: 'string', description: 'act 用：动作名或大意，例如「跳舞」「玩魔方」「螃蟹走路」' },
        text: { type: 'string', description: 'say 用：想让深深冒泡说的话，一两句就够' },
        x: { type: 'number', description: 'go 用：0~1，0.5 是屏幕横向中间' },
        y: { type: 'number', description: 'go 用：0~1，0.5 是屏幕上下中间' },
      },
      async execute(args) {
        const action = typeof args.action === 'string' ? args.action.trim() : ''
        if (!action) return { ok: false, text: '要让它做什么？给个 action：act / go / say / look / stroll……' }
        try {
          switch (action) {
            case 'look':
              return await petLook(conf)
            case 'act':
              if (!args.name) return { ok: false, text: 'act 要配一个 name，比如「跳舞」或「写代码」。' }
              return await petAct(conf, args.name)
            case 'go':
              return await petGo(conf, { x: args.x, y: args.y })
            case 'say':
              return await petSay(conf, args.text)
            case 'sleep':
              return await petSleep(conf, false)
            case 'wake':
              return await petSleep(conf, true)
            case 'stroll':
            case 'dance':
            case 'think':
            case 'come':
              return startActivity(conf, action)
            case 'list': {
              const names = animNames(conf)
              if (!names.length) return { ok: false, text: '没读到它的动作清单（dsh-pet 可能没装）。' }
              const sample = names.slice(0, 24).join('、')
              return {
                ok: true,
                text: `深深现在会 ${names.length} 个动作。举一些：${sample}……\n名字按大意说就行，对不上它会挑最像的。`,
              }
            }
            default:
              return {
                ok: false,
                text: `没有「${action}」这种动作。可选：act / stroll / dance / think / go / say / look / sleep / wake / list。`,
              }
          }
        } catch (error) {
          return { ok: false, text: `指挥不动它：${error instanceof Error ? error.message : String(error)}` }
        }
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

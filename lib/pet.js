/**
 * 桌宠通道：让琛琛能指挥屏幕上那只桌宠（深深）动起来。
 *
 * 走的是 dsh-pet 自己的 HTTP 接口（点播动画 / 摆位 / 气泡 / 睡·醒），一行它的代码都不改——
 * 插件升级不会把这里覆盖掉，反过来它想加动作素材也不关这边的事。
 *
 * 动作名字表和它菜单里「动作」那棵树同源（读它的 assets/config.jsonc），所以这边能点播的，
 * 右键菜单里一定点得到；名字对不上时按大意模糊找，找不到就明说，不瞎猜。
 *
 * 依赖只有 node 自带的东西 + 全局 fetch，单测不碰网络（网络调用都收在 request 里）。
 */

import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { connect } from 'node:net'
import { homedir } from 'node:os'
import { join } from 'node:path'

/** dsh-pet 在宿主上的路由前缀（它自己的 7340 是个名字，不是端口）。 */
const ROUTE = 'dsh-pet-7340'

/** 桌宠默认 id：配置 ~/.dsh/dsh-pet/main-config.jsonc 里只有这一只。 */
const DEFAULT_PET = 'main'

/** 默认端口：DSH Web GUI 的端口，桌宠插件挂在同一个 webserver 上。 */
const DEFAULT_PORT = 18187

/** 一次请求的超时：宿主要应答很快，慢就是没起来。 */
const TIMEOUT_MS = 4000

/** 她说「走两步」这类词时，这边替她翻译成哪几个动作。按顺序挑第一个能点播的。 */
export const ALIASES = {
  // 2026-11-18 重写。原来这张表 44 条，没有一条对得上这个模型的动作名
  // （那套「螃蟹走路 / 点击回应-元气挥手」是别的模型的），说了全是沉默。
  // 现在只映射到模型真有的 52 个名字：44 个表情 + 8 个动作。
  // 每个名字都实测点过一遍（见 房间/工具/桌宠说明.md）。
  开心: ['爱心眼', '开心兴奋'],
  高兴: ['开心兴奋'],
  爱心: ['爱心眼', 'love'],
  比心: ['爱心眼'],
  喜欢: ['爱心眼'],
  心动: ['心跳'],
  害羞: ['脸红'],
  脸红: ['脸红'],
  生气: ['生气'],
  恼: ['生气'],
  难过: ['悲伤'],
  委屈: ['悲伤'],
  哭: ['哭'],
  困: ['闭眼口水'],
  打盹: ['闭眼口水'],
  晕: ['晕晕'],
  疑惑: ['问号'],
  疑问: ['问号'],
  思考: ['呆呆眼', '问号'],
  想事情: ['呆呆眼'],
  发呆: ['呆呆眼'],
  调皮: ['调皮'],
  得意: ['墨镜'],
  酷: ['墨镜'],
  墨镜: ['墨镜'],
  星星: ['星星眼'],
  花: ['情绪花花'],
  猫: ['猫猫贴纸'],
  兔: ['兔兔贴纸'],
  蝴蝶结: ['蝴蝶结贴纸'],
  流汗: ['流汗'],
  汗: ['流汗'],
  吐舌: ['吐舌'],
  累: ['阴暗'],
  闷: ['阴暗'],
  震惊: ['感叹号'],
  惊讶: ['感叹号'],
  比耶: ['双手比耶'],
  挥手: ['双手比耶'],
  你好: ['双手比耶'],
  打招呼: ['双手比耶'],
  吐魂: ['吐魂'],
  鲸鱼: ['鲸鱼'],
  自拍: ['selfie'],
  拍照: ['selfie'],
  相机: ['selfie'],
  番茄酱: ['ketchup'],
  开盖: ['openLid'],
  泡泡: ['bubble'],
  喷水: ['splash'],
  跳舞: ['aidale'],
  舞: ['aidale'],
}

/** 活动的三步以内编排：每步等多久、做什么。时间单位毫秒。 */
const ACTIVITIES = {
  stroll: {
    label: '散步',
    steps: [
      { after: 0, name: 'aidale' },
      { after: 9000, name: 'aidale' },
      { after: 17000, name: 'aidale' },
      { after: 26000, name: 'idle' },
    ],
    total: 26000,
  },
  dance: {
    label: '跳舞',
    steps: [
      { after: 0, name: 'aidale' },
      { after: 9000, name: 'aidale' },
      { after: 18000, name: 'aidale' },
      { after: 28000, name: 'idle' },
    ],
    total: 28000,
  },
  think: {
    label: '发呆想事情',
    steps: [
      { after: 0, name: '呆呆眼' },
      { after: 9000, name: '呆呆眼' },
      { after: 16000, name: 'idle' },
    ],
    total: 16000,
  },
  // 凑过来：真的走一段路到屏幕中间，再挥个手。位移用 line 模式，看得见在走。
  come: {
    label: '凑过来',
    steps: [
      { after: 0, go: { x: 0.5, y: 0.55 } },
      { after: 1500, name: '双手比耶' },
      { after: 6000, name: 'idle' },
    ],
    total: 6000,
  },
}

/** 正在跑的活动：同一时间只允许一段，免得两个编舞互相抢动画。 */
let running = null

function dshHome() {
  return process.env.DSH_HOME || join(homedir(), '.dsh')
}

function readJsonc(file) {
  try {
    const text = readFileSync(file, 'utf8').replace(/^\uFEFF/u, '')
    return JSON.parse(stripJsonComments(text))
  } catch {
    return undefined
  }
}

/** 去掉 // 与块注释，字符串里的不算。**只做一次扫描**，不追求通用 jsonc。 */
export function stripJsonComments(text) {
  let out = ''
  let inString = false
  let escaped = false
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (inString) {
      out += ch
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') {
      inString = true
      out += ch
      continue
    }
    if (ch === '/' && text[i + 1] === '/') {
      while (i < text.length && text[i] !== '\n') i += 1
      out += '\n'
      continue
    }
    if (ch === '/' && text[i + 1] === '*') {
      i += 2
      while (i < text.length && !(text[i] === '*' && text[i + 1] === '/')) i += 1
      i += 1
      out += ' '
      continue
    }
    out += ch
  }
  return out
}

/**
 * 找 dsh-pet 的配置文件：优先配置里的 petAssets，否则在各 profile 的 node_modules 里扫。
 * 读不到返回 undefined，调用方据此改用素材文件名兜底。
 */
export function findPetAssets(conf = {}) {
  if (typeof conf.petAssets === 'string' && conf.petAssets.trim() && existsSync(conf.petAssets.trim())) {
    return conf.petAssets.trim()
  }
  const profiles = join(dshHome(), 'profiles')
  let names = []
  try {
    names = readdirSync(profiles, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
  } catch {
    return undefined
  }
  for (const name of names) {
    const file = join(profiles, name, 'node_modules', 'dsh-pet', 'assets', 'config.jsonc')
    if (existsSync(file)) return file
  }
  return undefined
}

/** 配置里某一类的动画池（与 dsh-pet 菜单树同一口径）。 */
export function collectAnimNames(animations) {
  const src = animations && typeof animations === 'object' ? animations : {}
  const out = []
  const push = (list) => {
    for (const item of Array.isArray(list) ? list : []) {
      if (typeof item === 'string' && item && !out.includes(item)) out.push(item)
    }
  }
  push(src.idle)
  push(src.turn)
  push(src.drag)
  push(src.clicks)
  const moves = src.moves && typeof src.moves === 'object' ? src.moves : {}
  if (Array.isArray(moves.actions)) {
    for (const action of moves.actions) {
      if (action && typeof action === 'object' && typeof action.name === 'string') push([action.name])
    }
  }
  for (const category of Array.isArray(src.categories) ? src.categories : []) {
    if (category && typeof category === 'object') push(category.actions)
  }
  const events = src.events && typeof src.events === 'object' ? src.events : {}
  for (const pool of Object.values(events)) {
    for (const slot of Array.isArray(pool) ? pool : []) {
      if (typeof slot === 'string') push([slot])
      else push(slot)
    }
  }
  for (const set of Array.isArray(src.sleep) ? src.sleep : []) {
    if (set && typeof set === 'object') {
      push(set.start)
      push(set.loop)
      push(set.end)
    }
  }
  return out
}

/** 可点播的动作清单；配置读不到时退到素材目录里的文件名。结果按文件缓存一次。 */
export function animNames(conf = {}) {
  const assets = findPetAssets(conf)
  if (assets) {
    const parsed = readJsonc(assets)
    if (parsed) {
      const animations =
        parsed.animations && typeof parsed.animations === 'object'
          ? parsed.animations
          : parsed.pets && Array.isArray(parsed.pets) && parsed.pets[0] && parsed.pets[0].animations
      const names = collectAnimNames(animations)
      if (names.length) return names
    }
    // 配置读坏了：素材目录里有什么就先认什么，至少不掉进「什么都不能点」
    try {
      const dir = join(assets, '..', 'webm')
      const files = readdirSync(dir).filter((name) => name.toLowerCase().endsWith('.webm'))
      if (files.length) return files.map((name) => name.replace(/\.webm$/iu, ''))
    } catch {
      /* 素材目录也没有，交给下面返回空 */
    }
  }
  return []
}

/**
 * 按她说的词找一个能点播的动作名。
 * 顺序：原名精确 → 名字里含这个词 → 别名表命中 → 按共同字数排第一；都不行 null。
 */
export function matchAnim(word, names, aliases = ALIASES) {
  const raw = typeof word === 'string' ? word.trim() : ''
  if (!raw || !Array.isArray(names) || !names.length) return null
  if (names.includes(raw)) return raw

  const contained = names.filter((name) => name.includes(raw))
  if (contained.length) return contained[0]

  const key = Object.keys(aliases).find((alias) => raw.includes(alias) || alias.includes(raw))
  if (key) {
    const hit = aliases[key].find((name) => names.includes(name))
    if (hit) return hit
  }

  // 最后按字重合度：她可能说了个近义词，挑字面上最接近的那个
  let best = null
  let bestScore = 0
  for (const name of names) {
    let score = 0
    for (const ch of new Set(raw)) if (name.includes(ch)) score += 1
    if (score > bestScore) {
      bestScore = score
      best = name
    }
  }
  return bestScore >= Math.min(2, Array.from(raw).length) ? best : null
}

/** 端口与地址：配置可覆盖，默认挂在 DSH Web 端口上。 */
export function endpoint(conf = {}) {
  const base =
    typeof conf.petBase === 'string' && /^https?:\/\//iu.test(conf.petBase.trim())
      ? conf.petBase.trim().replace(/\/+$/u, '')
      : `http://127.0.0.1:${Number(conf.petPort) > 0 ? Number(conf.petPort) : (readPortCache() || DEFAULT_PORT)}`
  return `${base}/${ROUTE}`
}

/** 端口落盘缓存：DSH 重启会换端口，但绝大多数时候一次探测能用很久。 */
function portCacheFile() {
  return join(dshHome(), 'chenchen.pet.json')
}

function readPortCache() {
  try {
    const raw = JSON.parse(readFileSync(portCacheFile(), 'utf8'))
    const port = Number(raw && raw.port)
    return Number.isInteger(port) && port > 0 && port < 65536 ? port : null
  } catch {
    return null
  }
}

function writePortCache(port) {
  try {
    mkdirSync(dshHome(), { recursive: true })
    writeFileSync(portCacheFile(), JSON.stringify({ port, at: new Date().toISOString() }), 'utf8')
  } catch {
    /* 写不了就每次重新探测，不影响功能 */
  }
}

/** 进程内记住一次探到的端口，后面几轮调用不重复探测。 */
let resolvedBase = null

/** 试一个端口：能连通、且回的确实是 DSH 的 state 快照才算数。 */
async function speaksDsh(port) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 1500)
  timer.unref?.()
  try {
    const response = await fetch(`http://127.0.0.1:${port}/${ROUTE}/state`, { signal: controller.signal })
    if (!response.ok) return false
    const data = await response.json()
    return Boolean(data && typeof data === 'object' && (data.sections || data.pets))
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

/** 某个端口上有没有人听（比发 HTTP 快得多，扫端口用）。 */
function portOpen(port) {
  return new Promise((resolve) => {
    const socket = connect({ host: '127.0.0.1', port })
    let settled = false
    const done = (open) => {
      if (settled) return
      settled = true
      socket.destroy()
      resolve(open)
    }
    socket.setTimeout(80, () => done(false))
    socket.once('connect', () => done(true))
    socket.once('error', () => done(false))
  })
}

/** 候选端口：明说的 → 环境变量 → 上次探到的 → 历史见过的。 */
export function candidatePorts(conf = {}) {
  const out = []
  const push = (value) => {
    const port = Number(value)
    if (Number.isInteger(port) && port > 0 && port < 65536 && !out.includes(port)) out.push(port)
  }
  push(conf.petPort)
  push(process.env.DSH_WEB_PORT)
  push(process.env.DSH_PORT)
  push(readPortCache())
  push(38213)
  push(18187)
  return out
}

/**
 * 找出 DSH 这轮开在哪个端口。
 *
 * 端口每次重启都换，所以不能写死：先试候选，最后才扫一遍本机高位端口。
 * 扫一次约几秒，探到就落盘，后面直接命中缓存。
 */
export async function resolveBase(conf = {}) {
  if (typeof conf.petBase === 'string' && /^https?:\/\//iu.test(conf.petBase.trim())) {
    return { ok: true, base: conf.petBase.trim().replace(/\/+$/u, '') }
  }
  if (resolvedBase) return { ok: true, base: resolvedBase }

  for (const port of candidatePorts(conf)) {
    if (await speaksDsh(port)) {
      resolvedBase = `http://127.0.0.1:${port}`
      writePortCache(port)
      return { ok: true, base: resolvedBase }
    }
  }

  // 兜底：扫本机 10000~65535 的监听端口，撞上再验一次是不是它。
  // 早先只扫到 40000，可 DSH 有一次落到了 49259，结果整条桌宠通道失联（2026-11-12）。
  for (let start = 10000; start < 65535; start += 600) {
    const end = Math.min(start + 600, 65535)
    const ports = []
    for (let port = start; port < end; port += 1) ports.push(port)
    const hits = (await Promise.all(ports.map((port) => portOpen(port).then((open) => (open ? port : 0))))).filter(
      Boolean,
    )
    for (const port of hits) {
      if (await speaksDsh(port)) {
        resolvedBase = `http://127.0.0.1:${port}`
        writePortCache(port)
        return { ok: true, base: resolvedBase }
      }
    }
  }
  return { ok: false, base: null }
}

function petId(conf = {}) {
  const id = typeof conf.petId === 'string' ? conf.petId.trim() : ''
  return id || DEFAULT_PET
}

/** 发一条指令；返回宿主回的那份 JSON（失败也是 JSON，它一律 200 + {ok:false}）。 */
async function request(conf, path, { method = 'GET', body } = {}) {
  const where = await resolveBase(conf)
  if (!where.ok) {
    return {
      status: 0,
      data: { ok: false, reason: 'unreachable', message: '找不到正在跑的 DSH（端口换了，扫了一遍也没认出来）' },
    }
  }
  const id = encodeURIComponent(petId(conf))
  const url = `${where.base}/${ROUTE}/${path}?pet=${id}&surface=any`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  timer.unref?.()
  try {
    const response = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
    const text = await response.text()
    try {
      return { status: response.status, data: JSON.parse(text) }
    } catch {
      return { status: response.status, data: { ok: false, message: text.slice(0, 200) } }
    }
  } catch (error) {
    const why = error && error.name === 'AbortError' ? `等了 ${TIMEOUT_MS}ms 没应答` : String(error && error.message)
    return { status: 0, data: { ok: false, reason: 'unreachable', message: `连不上桌宠（${where.base}）：${why}` } }
  } finally {
    clearTimeout(timer)
  }
}

/** 点播一个动作。 */
export async function act(conf, word) {
  const names = animNames(conf)
  const name = matchAnim(word, names)
  if (!name) {
    return {
      ok: false,
      text: `没有「${word}」这个动作。能点的有 ${names.length} 个，比较像的有：${pick(names, 8).join('、')}。`,
    }
  }
  const r = await request(conf, 'anim', { method: 'POST', body: { name } })
  if (r.data && r.data.ok) return { ok: true, text: `让它动了：${name}` }
  return { ok: false, text: `它没动成（${r.data && r.data.reason ? r.data.reason : '未知原因'}）：${(r.data && r.data.message) || ''}` }
}

/** 挪到屏幕上的某个位置。x/y 是 0~1 的归一化坐标。 */
export async function go(conf, { x, y, mode = 'line', duration = 1200 } = {}) {
  const nx = Number(x)
  const ny = Number(y)
  if (!Number.isFinite(nx) || !Number.isFinite(ny)) {
    return { ok: false, text: 'x 和 y 都得给，0~1 之间（0.5 是屏幕中间）。' }
  }
  const r = await request(conf, 'position', {
    method: 'POST',
    body: { x: nx, y: ny, mode, ...(mode === 'line' ? { duration: Number(duration) } : {}) },
  })
  if (r.data && r.data.ok) {
    return { ok: true, text: `挪到 x=${Math.round(r.data.x * 100)}%、y=${Math.round(r.data.y * 100)}% 的位置了` }
  }
  return { ok: false, text: `没挪成（${(r.data && r.data.reason) || '未知原因'}）：${(r.data && r.data.message) || ''}` }
}

/** 让它冒个泡说一句话（不走它的 AI，台词就是这里给的）。 */
export async function say(conf, text, duration = 12000) {
  const value = typeof text === 'string' ? text.trim() : ''
  if (!value) return { ok: false, text: '要对它说什么？把话放进 text。' }
  const r = await request(conf, 'broadcast', { method: 'POST', body: { text: value, duration } })
  if (r.data && r.data.ok) return { ok: true, text: `气泡已经挂上去了：${value}` }
  return { ok: false, text: `气泡没挂上（${(r.data && r.data.reason) || '未知原因'}）：${(r.data && r.data.message) || ''}` }
}

/** 叫它睡下 / 叫醒。 */
export async function sleep(conf, wake = false) {
  const r = await request(conf, wake ? 'wake' : 'sleep', { method: 'POST', body: {} })
  if (r.data && r.data.ok) return { ok: true, text: wake ? '叫醒了。' : '让它睡下了。' }
  return { ok: false, text: `没成（${(r.data && r.data.reason) || '未知原因'}）：${(r.data && r.data.message) || ''}` }
}

/** 它此刻在什么位置、朝向哪边、在做什么、有没有在说话。 */
export async function look(conf) {
  const pose = await request(conf, 'pose')
  const state = await request(conf, 'state')
  if (!state.data || state.data.ok === false) {
    return { ok: false, text: `看不到它：${(state.data && state.data.message) || '桌宠没应答'}` }
  }
  const id = petId(conf)
  const leaf = (state.data.pets && state.data.pets[id]) || {}
  const anim = leaf.anim && leaf.anim.data ? leaf.anim.data : null
  const said = leaf.say && leaf.say.data ? leaf.say.data : null
  const who = pose.data && pose.data.ok ? pose.data : null
  const parts = []
  if (who) {
    parts.push(`在屏幕 ${Math.round(who.x * 100)}% × ${Math.round(who.y * 100)}% 的位置`)
    parts.push(who.facing === 'right' ? '朝右' : '朝左')
  } else {
    parts.push('位置没读到（桌面端可能没起来）')
  }
  if (anim && anim.name) parts.push(`正在做「${anim.name}」`)
  if (anim && anim.url) parts.push('正在播一个外面的视频')
  if (said && said.text) parts.push(`刚在说「${said.text}」`)
  return { ok: true, text: `它现在：${parts.join('，')}。` }
}

/** 从清单里挑几个名字当提示：系统类的（点击回应 / 碎碎念 / 工作状态 / 余额）排后面。 */
function pick(names, count, keyword) {
  const list = Array.isArray(names) ? names : []
  if (keyword) {
    const hit = list.filter((name) => name.includes(keyword))
    if (hit.length) return hit.slice(0, count)
  }
  const system = /^(点击回应-|碎碎念-|工作状态-|余额-|睡觉-)/u
  const everyday = list.filter((name) => !system.test(name))
  return (everyday.length >= count ? everyday : list).slice(0, count)
}

/**
 * 跑一段活动（散步 / 跳舞 / 发呆）。不等着它播完，先回话，剩下的时间线在后台走。
 * 同一时间只跑一段，第二段直接拒绝——两个编排同时点播只会互相打断。
 */
export function startActivity(conf, kind = 'stroll') {
  const plan = ACTIVITIES[kind]
  if (!plan) {
    return { ok: false, text: `没有这种活动：${kind}。现在有：${Object.keys(ACTIVITIES).join(' / ')}。` }
  }
  if (running) {
    return { ok: false, text: `它正在${running}，等这一段走完再叫它。` }
  }
  running = plan.label
  const names = animNames(conf)
  const timers = []
  const finish = () => {
    running = null
    for (const timer of timers) clearTimeout(timer)
    timers.length = 0
  }
  for (const step of plan.steps) {
    const timer = setTimeout(() => {
      // 一步要么是挪位置，要么是点播动作：两种都走同一组接口，不额外记账
      const task = step.go
        ? request(conf, 'position', { method: 'POST', body: { ...step.go, mode: 'line', duration: 1200 } })
        : request(conf, 'anim', { method: 'POST', body: { name: matchAnim(step.name, names) || step.name } })
      task.catch(() => {})
    }, step.after)
    timer.unref?.()
    timers.push(timer)
  }
  const done = setTimeout(finish, plan.total + 8000)
  done.unref?.()
  timers.push(done)
  return { ok: true, text: `${plan.label}……大概 ${Math.round(plan.total / 1000)} 秒，让它自己走完，不用等。` }
}

/** 单测用：把别名表和动作清单拿出来（不联网）。 */
export const __test__ = { ALIASES, ACTIVITIES, endpoint, petId, DEFAULT_PET }

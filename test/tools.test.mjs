/**
 * 纯逻辑单测：配置、房间路径、读房间、叫停的防手滑。
 * 不 spawn python，沙箱里也能跑。跑法：node test/tools.test.mjs
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const TMP = join(HERE, '.tmp')
process.env.DSH_HOME = TMP

const { loadConfig, roomRoot, toolSpecs } = await import('../lib/tools.js')

test('loadConfig 默认值稳，坏值退回默认', () => {
  const conf = loadConfig({})
  assert.equal(conf.world, 'default')
  assert.equal(conf.enableStop, true)
  assert.ok(conf.timeoutMs >= 5000)
  assert.ok(conf.toolsDir.endsWith('tools'))

  const broken = loadConfig({ timeoutMs: -1, world: '', python: '   ' })
  assert.equal(broken.timeoutMs, 60000)
  assert.equal(broken.world, 'default')
  assert.ok(broken.python.length > 0)
})

test('roomRoot 跟着 world 走，非法字符被剔掉', () => {
  const conf = loadConfig({ world: 'default' })
  assert.equal(roomRoot(conf), join(TMP, 'worlds', 'default', 'room'))
  const weird = loadConfig({ world: 'a/b:c*' })
  assert.equal(roomRoot(weird), join(TMP, 'worlds', 'abc', 'room'))
})

test('room_read 列清单、读文件、拒绝越界', async () => {
  const conf = loadConfig({ world: 'testworld' })
  const room = roomRoot(conf)
  mkdirSync(room, { recursive: true })
  writeFileSync(join(room, '我是谁.md'), '# 我是谁\n\n我是琛琛。\n', 'utf8')

  const spec = toolSpecs(conf).find((tool) => tool.name === 'room_read')
  assert.ok(spec)

  const listed = await spec.execute({})
  assert.equal(listed.ok, true)
  assert.match(listed.text, /我是谁\.md/u)

  const read = await spec.execute({ file: '我是谁.md' })
  assert.equal(read.ok, true)
  assert.match(read.text, /我是琛琛/u)

  const escape = await spec.execute({ file: '../../../../etc/passwd' })
  assert.equal(escape.ok, false)

  const missing = await spec.execute({ file: '没有这篇.md' })
  assert.equal(missing.ok, false)
})

test('stop_me 不传 confirm 绝不动手', async () => {
  const conf = loadConfig({ world: 'testworld' })
  const spec = toolSpecs(conf).find((tool) => tool.name === 'stop_me')
  const result = await spec.execute({})
  assert.equal(result.ok, false)
  assert.match(result.text, /confirm/u)
})

test('stop_me 配置关掉时不执行', async () => {
  const conf = loadConfig({ world: 'testworld', enableStop: false })
  const spec = toolSpecs(conf).find((tool) => tool.name === 'stop_me')
  const result = await spec.execute({ confirm: true })
  assert.equal(result.ok, false)
  assert.match(result.text, /关掉了/u)
})

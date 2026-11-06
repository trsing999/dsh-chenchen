/**
 * apply 冒烟：没有宿主、没有 python 的情况下，插件也应该安静地注册完 6 个工具。
 * 跑法：node test/apply.test.mjs
 */
import { register } from 'node:module'
import test from 'node:test'
import assert from 'node:assert/strict'

register('./stub-loader.mjs', import.meta.url)
const { apply } = await import('../lib/index.js')

test('apply 注册 6 个工具，名字齐全', () => {
  const registered = []
  const ctx = {
    tools: { register: (tool) => registered.push(tool) },
    logger: { info() {}, warn() {}, error() {} },
  }
  apply(ctx, { python: 'python-not-installed-系' })
  assert.equal(registered.length, 6)
  assert.deepEqual(
    registered.map((tool) => tool.name).sort(),
    ['breath', 'dream', 'look_screen', 'now_playing', 'room_read', 'stop_me'],
  )
  for (const tool of registered) {
    assert.ok(tool.description && tool.description.length > 10, `${tool.name} 要有描述`)
    assert.equal(typeof tool.execute, 'function', `${tool.name} 要有 execute`)
  }
})

test('ctx.tools 晚到也不炸：走 inject 时只注册一次', () => {
  const registered = []
  const ctx = {
    tools: { register: (tool) => registered.push(tool) },
    inject: (_deps, callback) => callback(),
    logger: { info() {}, warn() {}, error() {} },
  }
  apply(ctx, {})
  assert.equal(registered.length, 6)
})

test('工具没抢名：6 个名字互不相同', () => {
  const registered = []
  const ctx = { tools: { register: (tool) => registered.push(tool) }, logger: { info() {} } }
  apply(ctx, {})
  const names = registered.map((tool) => tool.name)
  assert.equal(new Set(names).size, names.length)
})

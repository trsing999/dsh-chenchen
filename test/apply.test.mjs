/**
 * apply 冒烟：没有宿主、没有 python 的情况下，插件也应该安静地注册完 11 个工具。
 * 跑法：node test/apply.test.mjs
 */
import { register } from 'node:module'
import test from 'node:test'
import assert from 'node:assert/strict'

register('./stub-loader.mjs', import.meta.url)
const { apply } = await import('../lib/index.js')

test('apply 注册 11 个工具，名字齐全', () => {
  const registered = []
  const ctx = {
    tools: { register: (tool) => registered.push(tool) },
    logger: { info() {}, warn() {}, error() {} },
  }
  apply(ctx, { python: 'python-not-installed-系' })
  assert.equal(registered.length, 11)
  assert.deepEqual(
    registered.map((tool) => tool.name).sort(),
    ['breath', 'cook', 'dream', 'lesson', 'look_screen', 'now_playing', 'pet', 'room_read', 'say', 'stop_me', 'voice'],
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
  assert.equal(registered.length, 11)
})

test('工具没抢名：11 个名字互不相同', () => {
  const registered = []
  const ctx = { tools: { register: (tool) => registered.push(tool) }, logger: { info() {} } }
  apply(ctx, {})
  const names = registered.map((tool) => tool.name)
  assert.equal(new Set(names).size, names.length)
})

/**
 * 宿主按 agent 自己的 ctx 组装工具表：插件 ctx 上注册的那批进不了 agent。
 * 这里模拟一个带事件的 ctx，确认 agent 建出来时、每一步开始前，都会往 agent.ctx 补挂。
 */
function eventCtx() {
  const handlers = new Map()
  const ctx = {
    tools: { register() {} },
    logger: { info() {}, warn() {}, error() {} },
    on(event, handler) {
      if (!handlers.has(event)) handlers.set(event, [])
      handlers.get(event).push(handler)
      return () => {}
    },
  }
  return { ctx, handlers }
}

function fakeAgent() {
  const tools = []
  return { id: `agent-${tools.length}`, ctx: { tools: { register: (tool) => tools.push(tool) } }, tools }
}

test('agent 建出来时把工具挂到它自己的 ctx 上', () => {
  const { ctx, handlers } = eventCtx()
  apply(ctx, { python: 'python-not-installed-系' })
  assert.ok(handlers.get('agent/created')?.length, '要订阅 agent/created')

  const agent = fakeAgent()
  for (const handler of handlers.get('agent/created')) handler({ agent })

  assert.equal(agent.tools.length, 11)
  assert.deepEqual(
    agent.tools.map((tool) => tool.name).sort(),
    ['breath', 'cook', 'dream', 'lesson', 'look_screen', 'now_playing', 'pet', 'room_read', 'say', 'stop_me', 'voice'],
  )
  assert.equal(typeof agent.tools[0].execute, 'function')
})

test('同一个 agent 只挂一次，pre-step 不会重复挂', () => {
  const { ctx, handlers } = eventCtx()
  apply(ctx, {})
  const agent = fakeAgent()
  for (const handler of handlers.get('agent/created')) handler({ agent })
  for (const handler of handlers.get('agent/pre-step')) {
    handler({ agent }, () => undefined)
    handler({ agent }, () => undefined)
  }
  assert.equal(agent.tools.length, 11, '重复触发不能变成 33 个')
})





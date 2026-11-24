/**
 * 桌宠通道的离线单测：动作清单读取、名字模糊匹配、连不上时的说法。
 * 不真去动桌宠——这层不是它的测试集。跑法：node test/pet.test.mjs
 */
import test from 'node:test'
import assert from 'node:assert/strict'

const { ALIASES, act, animNames, candidatePorts, endpoint, matchAnim, stripJsonComments, startActivity } = await import(
  '../lib/pet.js'
)

test('动作清单读得到，且和菜单里点得到的一致', () => {
  const names = animNames({})
  assert.ok(names.length > 50, `动作太少：${names.length}`)
  for (const must of ['待机呼吸休闲', '螃蟹走路', '原地专心玩魔方', '睡觉-开始']) {
    assert.ok(names.includes(must), `清单里应该有「${must}」`)
  }
})

test('名字对不上时按大意找', () => {
  const names = animNames({})
  assert.equal(matchAnim('原地专心玩魔方', names), '原地专心玩魔方')
  assert.equal(matchAnim('跳舞', names), '轻快摇摆舞')
  assert.equal(matchAnim('走两步', names), '螃蟹走路')
  assert.equal(matchAnim('伸个懒腰', names), '超大伸懒腰')
  assert.equal(matchAnim('不存在的动作xyz', names), null)
  assert.equal(matchAnim('', names), null)
})

test('别名表里每个动作都真的存在（配置换了就露馅）', () => {
  const names = animNames({})
  const missing = []
  for (const [word, list] of Object.entries(ALIASES)) {
    if (!list.some((name) => names.includes(name))) missing.push(`${word} → ${list.join(' / ')}`)
  }
  assert.deepEqual(missing, [], `别名表指向了不存在的动作：${missing.join('；')}`)
})

test('jsonc 去注释不碰字符串里的斜杠', () => {
  const text = '{ "a": "http://x//y", // 注释\n "b": 1 /* 块 */ }'
  assert.deepEqual(JSON.parse(stripJsonComments(text)), { a: 'http://x//y', b: 1 })
})

test('端口可以配，普通情况落在 dsh-pet-7340 前缀上', () => {
  assert.ok(endpoint({}).endsWith('/dsh-pet-7340'))
  assert.equal(endpoint({ petBase: 'http://127.0.0.1:9000/' }), 'http://127.0.0.1:9000/dsh-pet-7340')
  assert.equal(endpoint({ petPort: 8080 }), 'http://127.0.0.1:8080/dsh-pet-7340')
})

test('候选端口去重，明说的排最前', () => {
  const ports = candidatePorts({ petPort: 12345 })
  assert.equal(ports[0], 12345)
  assert.equal(new Set(ports).size, ports.length)
  assert.ok(ports.every((port) => Number.isInteger(port) && port > 0 && port < 65536))
})

test('桌宠没起来时，act 不装作成功', async () => {
  // 明说一个没人听的地址：连接被拒，走的是「连不上」那条路，也不会去扫端口
  const r = await act({ petBase: 'http://127.0.0.1:1' }, '跳舞')
  assert.equal(r.ok, false)
  assert.match(r.text, /连不上|没动成/u)
})

test('没有的那种活动直接拒绝，不会装作安排上了', () => {
  const r = startActivity({}, '跑马拉松')
  assert.equal(r.ok, false)
  assert.match(r.text, /没有这种活动/u)
})

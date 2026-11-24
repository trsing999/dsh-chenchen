// 给 voice.py 用的 edge-tts 桥：生成 mp3。连不上微软就走不通，由 Python 那边降级。
// 用法：node _edge_tts.cjs <包目录> <文字> <声音> <输出路径>
const path = require('node:path')

const [pkgDir, text, voice, out] = process.argv.slice(2)
if (!pkgDir || !text || !out) {
  console.error('参数不对')
  process.exit(2)
}

const { EdgeTTS } = require(pkgDir)

;(async () => {
  const tts = new EdgeTTS()
  await tts.generate(text, voice || 'zh-CN-XiaoxiaoNeural')
  await tts.toFile(out, 'mp3')
})().catch((error) => {
  console.error(String((error && error.code) || (error && error.message) || error))
  process.exit(1)
})

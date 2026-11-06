/** 把 '@deepseek-ai/dsh-tools' 解析到测试桩，这样没有宿主也能跑 apply。 */
export async function resolve(specifier, context, next) {
  if (specifier === '@deepseek-ai/dsh-tools') {
    return { url: new URL('./stub-dsh-tools.mjs', import.meta.url).href, shortCircuit: true }
  }
  return next(specifier, context)
}

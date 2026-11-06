/** 测试用桩：没有宿主时，defineTool 原样返回 spec。 */
export function defineTool(spec) {
  return { __stub: true, ...spec }
}

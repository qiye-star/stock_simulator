/**
 * 自选列表的纯逻辑：切换与是否已选。
 */

/**
 * 切换某代码的自选状态，返回新数组（不修改入参）。
 * @param {string[]} list
 * @param {string} code
 * @returns {{ next: string[], added: boolean }}
 */
export function toggleWatch(list, code) {
  if (list.includes(code)) return { next: list.filter((c) => c !== code), added: false };
  return { next: [...list, code], added: true };
}

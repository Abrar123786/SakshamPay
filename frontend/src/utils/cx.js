/** Join class names, skipping falsy values: cx('a', cond && 'b', undefined) -> 'a b'. */
export function cx(...classes) {
  return classes.filter(Boolean).join(' ')
}

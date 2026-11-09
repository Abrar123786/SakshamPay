import { describe, expect, it } from 'vitest'

import { cx } from './cx'
import { formatINR } from './format'

describe('cx', () => {
  it('joins truthy class names and skips the rest', () => {
    const isActive = false
    expect(cx('a', isActive && 'b', null, undefined, '', 'c')).toBe('a c')
  })
})

describe('formatINR', () => {
  it('formats integer paise with Indian digit grouping', () => {
    expect(formatINR(10_000_000)).toBe('₹1,00,000.00')
    expect(formatINR(4_800_000)).toBe('₹48,000.00')
    expect(formatINR(12_345)).toBe('₹123.45')
    expect(formatINR(0)).toBe('₹0.00')
  })

  it('can hide paise', () => {
    expect(formatINR(4_850, { showPaise: false })).toBe('₹49')
    expect(formatINR(1_23_45_67_800, { showPaise: false })).toBe('₹1,23,45,678')
  })

  it.each([12.5, '100', null, undefined, Number.NaN, 2 ** 60])('rejects %s (money is integer paise)', (value) => {
    expect(() => formatINR(value)).toThrow(TypeError)
  })
})

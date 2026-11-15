/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-14
import { describe, expect, it } from 'vitest'
import { toTitleCase } from './titleCase'

describe('toTitleCase', () => {
  it.each([
    ['chicken and rice', 'Chicken and Rice'],
    ['the best chili', 'The Best Chili'],          // minor word first stays capitalized
    ['  LOUD   spacing ', 'Loud Spacing'],          // trims, collapses, lowercases first
    ['pasta of the day', 'Pasta of the Day'],
    ['', ''],
    [null, ''],
  ])('%j -> %j', (input, expected) => {
    expect(toTitleCase(input)).toBe(expected)
  })
})

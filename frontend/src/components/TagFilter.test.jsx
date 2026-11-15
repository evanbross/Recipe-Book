/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-14
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getTagCategories, getTags } from '../api/client'
import { renderWithProviders } from '../test/render'
import TagFilter from './TagFilter'

vi.mock('../api/client')

const TAGS = [
  { id: 10, name: 'Italian', slug: 'italian', category_id: 1 },
  { id: 11, name: 'Indian', slug: 'indian', category_id: 1 },
  { id: 12, name: 'Quick', slug: 'quick', category_id: null },
]

function renderFilter({ selectedIds = [], mode = 'and' } = {}) {
  const onChangeIds = vi.fn()
  const onChangeMode = vi.fn()
  renderWithProviders(
    <TagFilter selectedIds={selectedIds} onChangeIds={onChangeIds} mode={mode} onChangeMode={onChangeMode} />,
  )
  return { onChangeIds, onChangeMode }
}

describe('TagFilter', () => {
  beforeEach(() => {
    getTags.mockResolvedValue(TAGS)
    getTagCategories.mockResolvedValue([{ id: 1, name: 'Cuisine', slug: 'cuisine' }])
  })

  it('Enter adds the first tag matching the typed text', async () => {
    const user = userEvent.setup()
    const { onChangeIds } = renderFilter()
    await screen.findByPlaceholderText('Filter by tag…')

    await user.type(screen.getByRole('textbox'), 'ind{Enter}')

    expect(onChangeIds).toHaveBeenCalledWith([11])
  })

  it('clicking a dropdown item adds it, and selected tags are left out of the list', async () => {
    const user = userEvent.setup()
    const { onChangeIds } = renderFilter({ selectedIds: [10] })
    expect(await screen.findByText('Italian')).toBeInTheDocument()  // the chip

    await user.click(screen.getByRole('textbox'))

    expect(screen.queryByRole('button', { name: 'Italian' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Quick' }))
    expect(onChangeIds).toHaveBeenCalledWith([10, 12])
  })

  it('says when nothing matches', async () => {
    const user = userEvent.setup()
    renderFilter()

    await user.type(await screen.findByRole('textbox'), 'zzz')

    expect(screen.getByText(/No tags match/)).toHaveTextContent('No tags match “zzz”')
  })

  it('Backspace in an empty input removes the last selected tag', async () => {
    const user = userEvent.setup()
    const { onChangeIds } = renderFilter({ selectedIds: [10, 12] })
    await screen.findByText('Quick')

    await user.type(screen.getByRole('textbox'), '{Backspace}')

    expect(onChangeIds).toHaveBeenCalledWith([10])
  })

  it('offers ALL/ANY only once two or more tags are selected', async () => {
    renderFilter({ selectedIds: [10] })
    await screen.findByText('Italian')
    expect(screen.queryByRole('button', { name: 'ANY' })).not.toBeInTheDocument()
  })

  it('switches match mode', async () => {
    const user = userEvent.setup()
    const { onChangeMode } = renderFilter({ selectedIds: [10, 12] })

    await user.click(await screen.findByRole('button', { name: 'ANY' }))

    expect(onChangeMode).toHaveBeenCalledWith('or')
  })
})

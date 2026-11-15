/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-14
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import toast from 'react-hot-toast'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createTag, getTagCategories, getTags, suggestTags } from '../api/client'
import { renderWithProviders } from '../test/render'
import TagCategorizeDialog from './TagCategorizeDialog'

vi.mock('../api/client')
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn(), success: vi.fn() } }))

const CATEGORIES = [
  { id: 1, name: 'Cuisine', slug: 'cuisine' },
  { id: 2, name: 'Course', slug: 'course' },
]
const TAGS = [
  { id: 10, name: 'Italian', slug: 'italian', category_id: 1 },
  { id: 11, name: 'Quick', slug: 'quick', category_id: null },
]
const RECIPE = { id: 5, title: 'Cacio e Pepe', description: null, ingredients: 'pecorino', tags: [] }

/** mutationFn gets (variables, context) in TanStack v5; assert on variables only. */
const createTagPayloads = () => createTag.mock.calls.map(([variables]) => variables)

function conflict(detail) {
  return Object.assign(new Error('409'), { response: { status: 409, data: { detail } } })
}

function renderDialog(props = {}) {
  const onSave = vi.fn().mockResolvedValue(undefined)
  renderWithProviders(
    <TagCategorizeDialog recipe={RECIPE} onSave={onSave} onClose={vi.fn()} {...props} />,
  )
  return { onSave }
}

describe('TagCategorizeDialog', () => {
  beforeEach(() => {
    getTagCategories.mockResolvedValue(CATEGORIES)
    getTags.mockResolvedValue(TAGS)
    suggestTags.mockResolvedValue({
      existing_tag_ids: [10],
      new_tags: [{ name: 'pasta dishes', category_name: 'course' }],
    })
    createTag.mockResolvedValue({ id: 12, name: 'Pasta Dishes', slug: 'pasta-dishes', category_id: 2 })
  })

  it('preselects suggested existing tags and offers suggested new ones', async () => {
    renderDialog()

    expect(await screen.findByRole('button', { name: 'Remove Italian' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Pasta Dishes/ })).toBeInTheDocument()
    expect(suggestTags).toHaveBeenCalledTimes(1)
  })

  it('creates a suggested tag by name only, resolving its category case-insensitively', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByRole('button', { name: /Pasta Dishes/ }))

    await waitFor(() => expect(createTagPayloads()).toEqual([{ name: 'Pasta Dishes', category_id: 2 }]))
    await waitFor(() => expect(screen.queryByRole('button', { name: /Pasta Dishes/ })).not.toBeInTheDocument())
  })

  it('shows the server message and keeps the suggestion when creating fails', async () => {
    createTag.mockRejectedValue(conflict('A tag with this name already exists in that category'))
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByRole('button', { name: /Pasta Dishes/ }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
      'A tag with this name already exists in that category',
    ))
    expect(screen.getByRole('button', { name: /Pasta Dishes/ })).toBeEnabled()
  })

  it('adds a custom tag in the chosen category and clears the input', async () => {
    const user = userEvent.setup()
    renderDialog()
    const input = screen.getByPlaceholderText('Tag name…')

    await user.type(input, 'salt and pepper')
    await user.selectOptions(screen.getByRole('combobox'), 'Cuisine')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(createTagPayloads()).toEqual([{ name: 'Salt and Pepper', category_id: 1 }]))
    await waitFor(() => expect(input).toHaveValue(''))
  })

  it('keeps the typed custom tag name when creating fails', async () => {
    createTag.mockRejectedValue(conflict('A tag with this name already exists in that category'))
    const user = userEvent.setup()
    renderDialog()
    const input = screen.getByPlaceholderText('Tag name…')

    await user.type(input, 'Quick{Enter}')

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(input).toHaveValue('Quick')
  })

  it('saves the selected tag ids', async () => {
    const user = userEvent.setup()
    const { onSave } = renderDialog()
    await screen.findByRole('button', { name: 'Remove Italian' })

    await user.click(screen.getByRole('button', { name: 'Quick' }))
    await user.click(screen.getByRole('button', { name: 'Save Tags' }))

    expect(onSave).toHaveBeenCalledWith([10, 11])
  })

  it('still works when suggestions fail', async () => {
    suggestTags.mockRejectedValue(new Error('down'))
    renderDialog()

    expect(await screen.findByRole('button', { name: 'Italian' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(/Getting AI tag suggestions/)).not.toBeInTheDocument())
    expect(screen.getByText('No tags selected yet')).toBeInTheDocument()
  })
})

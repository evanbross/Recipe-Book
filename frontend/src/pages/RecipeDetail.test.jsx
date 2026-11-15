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
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { getRecipe } from '../api/client'
import { renderWithProviders } from '../test/render'
import RecipeDetail from './RecipeDetail'

vi.mock('../api/client')

describe('RecipeDetail', () => {
  it('links each tag to a search filtered by that tag id', async () => {
    getRecipe.mockResolvedValue({
      id: 5, title: 'Cacio e Pepe', source_type: 'manual', ingredients: null, instructions: null,
      tags: [{ id: 10, name: 'Italian', slug: 'italian', category_id: 1 }],
    })

    renderWithProviders(
      <Routes><Route path="/recipes/:id" element={<RecipeDetail />} /></Routes>,
      { route: '/recipes/5' },
    )

    // Search.jsx reads ?tag_ids= (comma-separated ids); a slug param is ignored.
    expect(await screen.findByRole('link', { name: 'Italian' })).toHaveAttribute('href', '/search?tag_ids=10')
  })
})

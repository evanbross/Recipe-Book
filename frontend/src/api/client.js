import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// ── Recipes ────────────────────────────────────────────────────────────────
export const getRecipes = (params) => api.get('/recipes', { params }).then(r => r.data)
export const getRecipe = (id) => api.get(`/recipes/${id}`).then(r => r.data)
export const createRecipe = (data) => api.post('/recipes', data).then(r => r.data)
export const updateRecipe = (id, data) => api.patch(`/recipes/${id}`, data).then(r => r.data)
export const deleteRecipe = (id) => api.delete(`/recipes/${id}`)

// ── Tags ───────────────────────────────────────────────────────────────────
export const getTags = (params) => api.get('/tags', { params }).then(r => r.data)
export const getTagCategories = () => api.get('/tags/categories').then(r => r.data)
export const createTag = (data) => api.post('/tags', data).then(r => r.data)
export const createTagCategory = (data) => api.post('/tags/categories', data).then(r => r.data)

// ── Capture ────────────────────────────────────────────────────────────────
export const captureFromUrl = (data) => api.post('/capture/url', data).then(r => r.data)

export const captureFromImage = (file, tagIds = []) => {
  const form = new FormData()
  form.append('file', file)
  form.append('tag_ids', tagIds.join(','))
  return api.post('/capture/image', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

// ── Search ─────────────────────────────────────────────────────────────────
export const searchRecipes = (params) => api.get('/search', { params }).then(r => r.data)

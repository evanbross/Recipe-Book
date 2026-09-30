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
export const suggestTags = (data) => api.post('/tags/suggest', data).then(r => r.data)

// ── Capture ────────────────────────────────────────────────────────────────
export const captureFromUrl = (data) => api.post('/capture/url', data).then(r => r.data)
export const scanForLinks = (data) => api.post('/capture/scan', data).then(r => r.data)

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

// ── Email scan ─────────────────────────────────────────────────────────────
export const getEmailAuthStatus = () => api.get('/email/auth/status').then(r => r.data)
export const getEmailConnectUrl = () => api.get('/email/auth/connect').then(r => r.data)
export const disconnectEmail = () => api.delete('/email/auth').then(r => r.data)

export const startEmailScan = () => api.post('/email/scan').then(r => r.data)
export const getEmailScanStatus = () => api.get('/email/scan/status').then(r => r.data)
export const getEmailScanReport = () => api.get('/email/scan/report').then(r => r.data)

export const getEmailSettings = () => api.get('/email/settings').then(r => r.data)
export const updateEmailSettings = (data) => api.patch('/email/settings', data).then(r => r.data)

export const getEmailCandidates = () => api.get('/email/candidates').then(r => r.data)
export const importEmailCandidate = (id) => api.post(`/email/candidates/${id}/import`).then(r => r.data)
export const discardEmailCandidate = (id) => api.delete(`/email/candidates/${id}`)
export const resetScanHistory = () => api.delete('/email/admin/reset-scan-history').then(r => r.data)

// ── Image candidates ───────────────────────────────────────────────────────
export const getImageCandidates = (id) => api.get(`/recipes/${id}/image-candidates`).then(r => r.data)
export const selectRecipeImage = (id, imageUrl) =>
  api.post(`/recipes/${id}/select-image`, { image_url: imageUrl }).then(r => r.data)
export const skipImageSelection = (id) => api.delete(`/recipes/${id}/image-pending`)

// ── Watch list ─────────────────────────────────────────────────────────────
export const getWatchedSites = () => api.get('/watchlist').then(r => r.data)
export const getDueSites = () => api.get('/watchlist/due').then(r => r.data)
export const createWatchedSite = (data) => api.post('/watchlist', data).then(r => r.data)
export const updateWatchedSite = (id, data) => api.patch(`/watchlist/${id}`, data).then(r => r.data)
export const deleteWatchedSite = (id) => api.delete(`/watchlist/${id}`)
export const markSiteVisited = (id) => api.post(`/watchlist/${id}/visit`).then(r => r.data)

// ── Admin ──────────────────────────────────────────────────────────────────
export const purgeAllRecipes = () => api.delete('/admin/purge-recipes').then(r => r.data)

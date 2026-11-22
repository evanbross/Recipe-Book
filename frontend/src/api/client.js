import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// ai: claude-opus-5-5 | 2026-11-17
// The browser starts sign-in by navigating here (a full page load, not XHR):
// the API redirects to Google, and the session cookie comes back on the redirect.
export const SIGN_IN_URL = '/api/auth/login'

// ai: claude-opus-5-5 | 2026-11-19
// Full-page navigations to Google from Settings: link another Google account,
// or prove it's you again. Both come back to /settings.
export const GOOGLE_LINK_URL = '/api/auth/google/link'
export const GOOGLE_REAUTH_URL = '/api/auth/reauth/google'

// A 401 means the session ended (expired, signed out elsewhere, or removed from
// the household). Send the user to the login page rather than leaving every
// query failing. Exceptions, where a 401 is an answer the page shows itself:
// /auth/me (RequireAuth redirects on its own), and a wrong password or passkey
// at sign-in or re-auth (invalid_credentials), which must not sign anyone out.
// ai: claude-opus-5-5 | 2026-11-19
const ANSWERS_401_ITSELF = ['/auth/me', '/auth/password/login', '/auth/passkeys/login/', '/auth/reauth/']

api.interceptors.response.use(undefined, (error) => {
  const url = error.config?.url ?? ''
  const handledByCaller = ANSWERS_401_ITSELF.some((prefix) => url.startsWith(prefix))  // ai: claude-opus-5-5 | 2026-11-19
  if (error.response?.status === 401 && !handledByCaller && window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
  return Promise.reject(error)
})

// ── Sign-in and household ──────────────────────────────────────────────────
export const getMe = () => api.get('/auth/me').then(r => r.data)
export const logout = () => api.post('/auth/logout')
export const getHousehold = () => api.get('/household').then(r => r.data)
export const inviteToHousehold = (email) => api.post('/household/invites', { email }).then(r => r.data)
export const revokeInvite = (id) => api.delete(`/household/invites/${id}`)
export const removeHouseholdMember = (userId) => api.delete(`/household/members/${userId}`)

// ── Sign-in methods ────────────────────────────────────────────────────────
// ai: claude-opus-5-5 | 2026-11-19
// Errors come back as axios rejections whose response.data.detail is a short
// code; utils/authMessages.js turns it into text.
export const passwordLogin = (email, password) => api.post('/auth/password/login', { email, password })
export const register = (email, password, displayName) =>
  api.post('/auth/password/register', { email, password, display_name: displayName || null })
export const verifyEmail = (token) => api.post('/auth/password/verify', { token })
export const forgotPassword = (email) => api.post('/auth/password/forgot', { email })
export const resetPassword = (token, password) => api.post('/auth/password/reset', { token, password })
export const passkeyLoginOptions = () => api.post('/auth/passkeys/login/options').then(r => r.data)
export const passkeyLoginVerify = (flowId, credential) =>
  api.post('/auth/passkeys/login/verify', { flow_id: flowId, credential })

export const getSignInMethods = () => api.get('/auth/methods').then(r => r.data)
export const setPassword = (password) => api.put('/auth/password', { password })
export const removePassword = () => api.delete('/auth/password')
export const passkeyRegisterOptions = () => api.post('/auth/passkeys/register/options').then(r => r.data)
export const passkeyRegisterVerify = (flowId, credential, name) =>
  api.post('/auth/passkeys/register/verify', { flow_id: flowId, credential, name: name || null }).then(r => r.data)
export const renamePasskey = (id, name) => api.patch(`/auth/passkeys/${id}`, { name }).then(r => r.data)
export const removePasskey = (id) => api.delete(`/auth/passkeys/${id}`)
export const unlinkIdentity = (id) => api.delete(`/auth/identities/${id}`)

export const reauthPassword = (password) => api.post('/auth/reauth/password', { password })
export const reauthPasskeyOptions = () => api.post('/auth/reauth/passkey/options').then(r => r.data)
export const reauthPasskeyVerify = (flowId, credential) =>
  api.post('/auth/reauth/passkey/verify', { flow_id: flowId, credential })

// ── Server administration ─────────────────────────────────────────────────
export const getSmtpSettings = () => api.get('/admin/smtp').then(r => r.data)
export const updateSmtpSettings = (data) => api.put('/admin/smtp', data).then(r => r.data)
export const testSmtpSettings = () => api.post('/admin/smtp/test')

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

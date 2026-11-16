/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */

// ai: claude-opus-5-5 | 2026-11-16
// Settings and storage keys shared by the service worker, popup and options page.

// The dev Caddy hostname main.py registers (http://<CADDY_APP_NAME>.localhost).
// manifest.json's host_permissions grants this origin at install time; any other
// address is granted at runtime when it is saved on the options page.
export const DEFAULT_APP_URL = 'http://recipe-app.localhost';

const APP_URL_KEY = 'appUrl';

export async function getAppUrl() {
    const stored = await chrome.storage.sync.get(APP_URL_KEY);
    return stored[APP_URL_KEY] || DEFAULT_APP_URL;
}

export async function setAppUrl(origin) {
    await chrome.storage.sync.set({ [APP_URL_KEY]: origin });
}

// One capture state per tab, in storage.session so it survives the popup closing
// and disappears when the browser restarts.
// Shape: { tabUrl, status: 'working' | 'saved' | 'error', title?, recipeUrl?, message? }
export function captureKey(tabId) {
    return `capture:${tabId}`;
}

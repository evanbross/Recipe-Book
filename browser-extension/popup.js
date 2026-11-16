/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */

// ai: claude-opus-5-5 | 2026-11-16
// Popup: starts a capture of the active tab and shows its progress. The capture
// itself runs in the service worker; this view only renders the tab's state from
// storage.session and re-renders when that state changes.

import { captureKey } from './config.js';

const pageEl = document.getElementById('page');
const captureBtn = document.getElementById('capture');
const statusEl = document.getElementById('status');
const openLink = document.getElementById('open');
const settingsBtn = document.getElementById('settings');

const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
const key = captureKey(tab.id);
const capturable = /^https?:\/\//.test(tab.url ?? '');

pageEl.textContent = capturable ? `${new URL(tab.url).hostname} — ${tab.title ?? ''}` : '';

function render(state) {
    // A state left over from a page this tab has since navigated away from doesn't apply.
    const current = state && state.tabUrl === tab.url ? state : null;

    statusEl.className = 'status';
    statusEl.textContent = '';
    openLink.hidden = true;
    captureBtn.disabled = !capturable;
    captureBtn.textContent = 'Capture recipe';

    if (!capturable) {
        statusEl.textContent = 'Open a recipe page to capture it.';
        return;
    }
    if (current?.status === 'working') {
        captureBtn.disabled = true;
        captureBtn.textContent = 'Capturing…';
        statusEl.textContent = 'Reading the recipe. This can take up to a minute; you can close this popup.';
    } else if (current?.status === 'saved') {
        captureBtn.textContent = 'Capture again';
        statusEl.classList.add('ok');
        statusEl.textContent = `Saved: ${current.title}`;
        openLink.href = current.recipeUrl;
        openLink.hidden = false;
    } else if (current?.status === 'error') {
        captureBtn.textContent = 'Try again';
        statusEl.classList.add('error');
        statusEl.textContent = current.message;
    }
}

captureBtn.addEventListener('click', async () => {
    captureBtn.disabled = true;
    await chrome.runtime.sendMessage({ type: 'capture', tabId: tab.id, tabUrl: tab.url });
});

settingsBtn.addEventListener('click', () => chrome.runtime.openOptionsPage());

chrome.storage.session.onChanged.addListener((changes) => {
    if (changes[key]) {
        render(changes[key].newValue);
    }
});

render((await chrome.storage.session.get(key))[key]);

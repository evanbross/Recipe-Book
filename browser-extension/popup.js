/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */

// ai: claude-opus-5-5 | 2026-11-16
// Popup: pick tags, start a capture of the active tab and show its progress. The
// capture itself runs in the service worker; this view only renders the tab's state
// from storage.session and re-renders when that state changes.

import { captureKey, getAppUrl } from './config.js';

const TAG_LOAD_TIMEOUT_MS = 5000;

const pageEl = document.getElementById('page');
const tagsFieldset = document.getElementById('tags');
const selectedTagsEl = document.getElementById('selected-tags');
const tagFilterInput = document.getElementById('tag-filter');
const tagListEl = document.getElementById('tag-list');
const captureBtn = document.getElementById('capture');
const statusEl = document.getElementById('status');
const openLink = document.getElementById('open');
const settingsBtn = document.getElementById('settings');

const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
const key = captureKey(tab.id);
const capturable = /^https?:\/\//.test(tab.url ?? '');

let allTags = [];
let categories = [];
let tagLoadError = null;
const selectedTagIds = new Set();

pageEl.textContent = capturable ? `${new URL(tab.url).hostname} — ${tab.title ?? ''}` : '';

// ── Tags ──────────────────────────────────────────────────────────────────────

async function fetchJsonArray(url) {
    const res = await fetch(url, { signal: AbortSignal.timeout(TAG_LOAD_TIMEOUT_MS) });
    if (!res.ok) {
        throw new Error(`HTTP ${res.status} from ${url}`);
    }
    // res.json() throws on the empty 200 Caddy sends when the app isn't running.
    const body = await res.json();
    if (!Array.isArray(body)) {
        throw new Error(`Expected a list from ${url}`);
    }
    return body;
}

async function loadTags() {
    const appUrl = await getAppUrl();
    try {
        [allTags, categories] = await Promise.all([
            fetchJsonArray(`${appUrl}/api/tags`),
            fetchJsonArray(`${appUrl}/api/tags/categories`),
        ]);
        tagLoadError = null;
    } catch (err) {
        console.warn('[popup] could not load tags', err);
        tagLoadError = "Couldn't load tags from Recipe App. The recipe can still be saved without them.";
    }
    renderTags();
}

function tagChip(tag) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = tag.name;
    chip.setAttribute('aria-pressed', String(selectedTagIds.has(tag.id)));
    chip.addEventListener('click', () => {
        if (selectedTagIds.has(tag.id)) {
            selectedTagIds.delete(tag.id);
        } else {
            selectedTagIds.add(tag.id);
        }
        renderTags();
    });
    return chip;
}

function tagGroup(label, tags) {
    const group = document.createElement('div');
    const heading = document.createElement('div');
    heading.className = 'group-label';
    heading.textContent = label;
    const chips = document.createElement('div');
    chips.className = 'chips';
    chips.append(...tags.map(tagChip));
    group.append(heading, chips);
    return group;
}

function emptyNote(text) {
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = text;
    return note;
}

function renderTags() {
    selectedTagsEl.replaceChildren(...allTags.filter((t) => selectedTagIds.has(t.id)).map(tagChip));

    if (tagLoadError) {
        tagFilterInput.hidden = true;
        tagListEl.replaceChildren(emptyNote(tagLoadError));
        return;
    }
    tagFilterInput.hidden = allTags.length === 0;
    if (allTags.length === 0) {
        tagListEl.replaceChildren(emptyNote('No tags yet. Add them in Recipe App.'));
        return;
    }

    const needle = tagFilterInput.value.trim().toLowerCase();
    const visible = allTags.filter((t) => t.name.toLowerCase().includes(needle));
    const knownCategoryIds = new Set(categories.map((c) => c.id));
    const groups = [
        ...categories.map((c) => [c.name, visible.filter((t) => t.category_id === c.id)]),
        ['Other', visible.filter((t) => !knownCategoryIds.has(t.category_id))],
    ].filter(([, tags]) => tags.length > 0);

    tagListEl.replaceChildren(
        ...(groups.length > 0
            ? groups.map(([label, tags]) => tagGroup(label, tags))
            : [emptyNote(`No tags match “${tagFilterInput.value.trim()}”.`)]),
    );
}

tagFilterInput.addEventListener('input', renderTags);

// ── Capture state ─────────────────────────────────────────────────────────────

function render(state) {
    // A state left over from a page this tab has since navigated away from doesn't apply.
    const current = state && state.tabUrl === tab.url ? state : null;

    statusEl.className = 'status';
    statusEl.textContent = '';
    openLink.hidden = true;
    tagsFieldset.hidden = !capturable;
    tagsFieldset.disabled = false;
    captureBtn.disabled = !capturable;
    captureBtn.textContent = 'Capture recipe';

    if (!capturable) {
        statusEl.textContent = 'Open a recipe page to capture it.';
        return;
    }
    if (current?.status === 'working') {
        tagsFieldset.disabled = true;
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
    tagsFieldset.disabled = true;
    await chrome.runtime.sendMessage({
        type: 'capture',
        tabId: tab.id,
        tabUrl: tab.url,
        tagIds: [...selectedTagIds],
    });
});

settingsBtn.addEventListener('click', () => chrome.runtime.openOptionsPage());

chrome.storage.session.onChanged.addListener((changes) => {
    if (changes[key]) {
        render(changes[key].newValue);
    }
});

render((await chrome.storage.session.get(key))[key]);
if (capturable) {
    await loadTags();
}

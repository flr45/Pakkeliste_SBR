const FAVORITE_KEY = 'sbr_portal_favorites_v1';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function showToast(message, tone = 'normal') {
  const toast = $('#toast');
  if (!toast) return;
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.classList.add('show');
  window.clearTimeout(window.__sbrToastTimer);
  window.__sbrToastTimer = window.setTimeout(() => toast.classList.remove('show'), 2400);
}

function readFavorites() {
  try {
    const value = JSON.parse(localStorage.getItem(FAVORITE_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeFavorites(favorites) {
  localStorage.setItem(FAVORITE_KEY, JSON.stringify(favorites));
}

function favoriteKey(item) {
  return `${item.type}:${item.id}`;
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function syncFavoriteButtons() {
  const activeKeys = new Set(readFavorites().map(favoriteKey));
  $$('.favorite-toggle').forEach((button) => {
    const active = activeKeys.has(`${button.dataset.favoriteType}:${button.dataset.favoriteId}`);
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
    if (button.classList.contains('favorite-star')) {
      button.textContent = active ? '★' : '☆';
    } else {
      button.textContent = active ? 'Fjern favorit' : 'Gem favorit';
    }
  });
}

function favoriteCard(item) {
  const typeLabel = item.type === 'vehicle' ? 'Køretøj' : 'Udstyr';
  const mark = item.type === 'vehicle' ? 'K' : 'U';
  return `<a class="favorite-card" href="${escapeHtml(item.url)}"><span class="favorite-mark">${mark}</span><span><small>${typeLabel}</small><strong>${escapeHtml(item.title)}</strong></span><i>Åbn</i></a>`;
}

function renderFavorites() {
  const preview = $('#favoritePreview');
  if (!preview) return;
  const favorites = readFavorites();
  const limit = Number(preview.dataset.limit || 4);
  const shown = favorites.slice(0, limit);
  preview.innerHTML = shown.length
    ? shown.map(favoriteCard).join('')
    : '<div class="compact-empty">Du har endnu ikke gemt køretøjer eller udstyr som favorit på denne enhed.</div>';
}

function toggleFavorite(button) {
  const item = {
    type: button.dataset.favoriteType,
    id: button.dataset.favoriteId,
    title: button.dataset.favoriteTitle,
    url: button.dataset.favoriteUrl,
  };
  const favorites = readFavorites();
  const key = favoriteKey(item);
  const index = favorites.findIndex((entry) => favoriteKey(entry) === key);
  if (index >= 0) {
    favorites.splice(index, 1);
    showToast('Fjernet fra favoritter');
  } else {
    favorites.unshift(item);
    showToast('Gemt som favorit');
  }
  writeFavorites(favorites);
  syncFavoriteButtons();
  renderFavorites();
}

function bindFilter({ input, rows, empty, counter }) {
  const field = $(input);
  if (!field) return;
  const entries = $$(rows);
  const emptyState = $(empty);
  const count = $(counter);

  const run = () => {
    const query = field.value.trim().toLowerCase();
    let visible = 0;
    entries.forEach((entry) => {
      const searchText = entry.dataset.search || entry.textContent.toLowerCase();
      const show = !query || searchText.includes(query);
      entry.hidden = !show;
      if (show) visible += 1;
    });
    emptyState?.classList.toggle('hidden', visible !== 0 || !query);
    if (count) count.textContent = String(visible);
  };

  field.addEventListener('input', run);
  run();
}

async function submitForm(url, form) {
  const response = await fetch(url, { method: 'POST', body: new FormData(form) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response;
}

function setBusy(button, busy, label = 'Arbejder…') {
  if (!button) return;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalLabel || button.textContent;
    button.disabled = false;
  }
}

function bindAdminForms() {
  const descriptionForm = $('#vehicleDescriptionForm');
  descriptionForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('button[type="submit"]', descriptionForm);
    setBusy(button, true, 'Gemmer…');
    try {
      await submitForm(`/vehicle/${descriptionForm.dataset.vehicleId}/description`, descriptionForm);
      showToast('Beskrivelsen er gemt');
    } catch {
      showToast('Beskrivelsen kunne ikke gemmes', 'error');
    } finally {
      setBusy(button, false);
    }
  });

  const placeForm = $('#newPlaceForm');
  placeForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('button[type="submit"]', placeForm);
    setBusy(button, true, 'Opretter…');
    try {
      const response = await submitForm(`/vehicle/${placeForm.dataset.vehicleId}/places/new`, placeForm);
      const result = await response.json();
      location.href = `/vehicle/${placeForm.dataset.vehicleId}/place/${result.id}`;
    } catch {
      setBusy(button, false);
      showToast('Rummet kunne ikke oprettes', 'error');
    }
  });

  const documentForm = $('#documentUploadForm');
  documentForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('button[type="submit"]', documentForm);
    setBusy(button, true, 'Uploader…');
    try {
      await submitForm(`/vehicle/${documentForm.dataset.vehicleId}/docs`, documentForm);
      showToast('Dokumentet er uploadet');
      window.setTimeout(() => location.reload(), 500);
    } catch {
      setBusy(button, false);
      showToast('Dokumentet kunne ikke uploades', 'error');
    }
  });

  const renameForm = $('#renamePlaceForm');
  renameForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('button[type="submit"]', renameForm);
    setBusy(button, true, 'Gemmer…');
    try {
      await submitForm(`/place/${renameForm.dataset.placeId}/rename`, renameForm);
      showToast('Navnet er gemt');
      window.setTimeout(() => location.reload(), 450);
    } catch {
      setBusy(button, false);
      showToast('Navnet kunne ikke gemmes', 'error');
    }
  });

  const itemForm = $('#addItemForm');
  itemForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('button[type="submit"]', itemForm);
    setBusy(button, true, 'Tilføjer…');
    try {
      const response = await submitForm(`/place/${itemForm.dataset.placeId}/items/new`, itemForm);
      const result = await response.json();
      location.href = `/item/${result.id}`;
    } catch {
      setBusy(button, false);
      showToast('Udstyret kunne ikke tilføjes', 'error');
    }
  });

  const photoInput = $('#itemPhotoInput');
  photoInput?.addEventListener('change', async () => {
    if (!photoInput.files?.length) return;
    const data = new FormData();
    data.append('file', photoInput.files[0]);
    showToast('Uploader billede…');
    try {
      const response = await fetch(`/item/${photoInput.dataset.itemId}/photo`, { method: 'POST', body: data });
      if (!response.ok) throw new Error();
      location.reload();
    } catch {
      showToast('Billedet kunne ikke uploades', 'error');
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  syncFavoriteButtons();
  renderFavorites();
  bindAdminForms();

  bindFilter({ input: '#vehicleFilter', rows: '#vehicleDirectory .vehicle-card', empty: '#vehicleEmptySearch', counter: '#vehicleVisibleCount' });
  bindFilter({ input: '#itemFilter', rows: '#itemDirectory .equipment-row', empty: '#itemEmptySearch' });
  bindFilter({ input: '#documentFilter', rows: '#documentDirectory .document-row', empty: '#documentEmptySearch', counter: '#documentVisibleCount' });

  $$('[data-toggle-panel]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = document.getElementById(button.dataset.togglePanel);
      target?.classList.toggle('hidden-panel');
    });
  });

  document.addEventListener('click', async (event) => {
    const favoriteButton = event.target.closest('.favorite-toggle');
    if (favoriteButton) {
      event.preventDefault();
      event.stopPropagation();
      toggleFavorite(favoriteButton);
      return;
    }

    if (event.target.closest('.copy-link')) {
      try {
        await navigator.clipboard.writeText(window.location.href);
        showToast('Link kopieret');
      } catch {
        showToast('Linket kunne ikke kopieres', 'error');
      }
    }
  });

  $('#clearFavorites')?.addEventListener('click', () => {
    if (window.confirm('Ryd alle favoritter på denne enhed?')) {
      writeFavorites([]);
      syncFavoriteButtons();
      renderFavorites();
      showToast('Favoritter ryddet');
    }
  });
});

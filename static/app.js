const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function bindDirectoryFilter(inputSelector, rowSelector, emptySelector) {
  const input = $(inputSelector);
  if (!input) return;
  const rows = $$(rowSelector);
  const empty = $(emptySelector);

  input.addEventListener('input', () => {
    const query = input.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      const haystack = row.dataset.search || row.textContent.toLowerCase();
      const show = !query || haystack.includes(query);
      row.hidden = !show;
      if (show) visible += 1;
    });
    if (empty) empty.classList.toggle('hidden', visible !== 0 || !query);
  });
}

async function postForm(url, form) {
  const response = await fetch(url, { method: 'POST', body: new FormData(form) });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response;
}

function flashButton(button, text = 'Gemt') {
  if (!button) return;
  const original = button.textContent;
  button.textContent = `${text} ✓`;
  button.disabled = true;
  setTimeout(() => {
    button.textContent = original;
    button.disabled = false;
  }, 1200);
}

function initVehiclePage() {
  const vehicleId = window.vehicleId;
  if (!vehicleId) return;

  const saveDescription = $('#saveDesc');
  saveDescription?.addEventListener('click', async () => {
    const form = new FormData();
    form.append('description', $('#desc')?.value || '');
    const response = await fetch(`/vehicle/${vehicleId}/description`, {
      method: 'POST',
      body: form,
    });
    if (response.ok) flashButton(saveDescription);
  });

  const newPlaceForm = $('#newPlaceForm');
  newPlaceForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await postForm(`/vehicle/${vehicleId}/places/new`, newPlaceForm);
      location.reload();
    } catch (error) {
      alert('Rummet kunne ikke oprettes.');
    }
  });

  const docForm = $('#docForm');
  docForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await postForm(`/vehicle/${vehicleId}/docs`, docForm);
      location.reload();
    } catch (error) {
      alert('Dokumentet kunne ikke uploades.');
    }
  });
}

function initPlacePage() {
  const renameForm = $('#renamePlaceForm');
  renameForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const placeId = renameForm.dataset.placeId;
    try {
      await postForm(`/place/${placeId}/rename`, renameForm);
      location.reload();
    } catch (error) {
      alert('Navnet kunne ikke gemmes.');
    }
  });

  const addItemForm = $('#addItemForm');
  addItemForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const placeId = addItemForm.dataset.placeId;
    try {
      const response = await postForm(`/place/${placeId}/items/new`, addItemForm);
      const result = await response.json();
      location.href = `/item/${result.id}`;
    } catch (error) {
      alert('Udstyret kunne ikke tilføjes.');
    }
  });
}

function initItemPage() {
  const photoInput = $('#itemPhotoInput');
  photoInput?.addEventListener('change', async () => {
    if (!photoInput.files?.length) return;
    const data = new FormData();
    data.append('file', photoInput.files[0]);
    const response = await fetch(`/item/${photoInput.dataset.itemId}/photo`, {
      method: 'POST',
      body: data,
    });
    if (response.ok) location.reload();
    else alert('Billedet kunne ikke uploades.');
  });
}

document.addEventListener('DOMContentLoaded', () => {
  $$('[data-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = document.getElementById(button.dataset.toggle);
      target?.classList.toggle('hidden');
    });
  });

  bindDirectoryFilter('#vehicleFilter', '#vehicleDirectory .vehicle-row', '#vehicleEmptySearch');
  bindDirectoryFilter('#itemFilter', '#itemDirectory .item-row', '#itemEmptySearch');
  bindDirectoryFilter('#documentFilter', '#documentDirectory .document-row', '#documentEmptySearch');

  initVehiclePage();
  initPlacePage();
  initItemPage();
});

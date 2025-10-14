// reserved for future enhancements



document.addEventListener('DOMContentLoaded', () => {
  const ls = document.getElementById('local-search');
  if (ls) {
    ls.addEventListener('input', () => {
      const q = ls.value.toLowerCase();
      document.querySelectorAll('#places details').forEach(d => {
        const name = d.querySelector('.place-name')?.textContent.toLowerCase() || '';
        let hit = name.includes(q);
        if (!hit) {
          hit = !!Array.from(d.querySelectorAll('.items li .it-name')).find(el => el.textContent.toLowerCase().includes(q));
        }
        d.style.display = hit ? '' : 'none';
      });
    });
  }

  document.querySelectorAll('.place-name').forEach(el => {
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); el.blur(); }
    });
    el.addEventListener('blur', async () => {
      const pid = el.dataset.pid;
      const name = el.textContent.trim();
      if (!pid) return;
      const fd = new FormData(); fd.append('name', name);
      const r = await fetch(`/place/${pid}/rename`, { method:'POST', body: fd });
      if (!r.ok) alert('Kunne ikke gemme navn');
    });
  });

  document.querySelectorAll('.btn-move').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const kind = btn.dataset.kind;
      const id = btn.dataset.id;
      const dir = btn.dataset.dir;
      const fd = new FormData(); fd.append('direction', dir);
      const url = kind === 'place' ? `/place/${id}/move` : `/item/${id}/move`;
      const r = await fetch(url, { method:'POST', body: fd });
      if (!r.ok) return;

      if (kind === 'place') {
        const detailsEl = btn.closest('details');
        const parent = detailsEl.parentElement;
        const siblings = Array.from(parent.children);
        const idx = siblings.indexOf(detailsEl);
        if (dir === 'up' && idx > 0) parent.insertBefore(detailsEl, siblings[idx-1]);
        if (dir === 'down' && idx < siblings.length - 1) parent.insertBefore(detailsEl, siblings[idx+2] || null);
      } else {
        const li = btn.closest('li');
        const ul = li.parentElement;
        const items = Array.from(ul.children);
        const idx = items.indexOf(li);
        if (dir === 'up' && idx > 0) ul.insertBefore(li, items[idx-1]);
        if (dir === 'down' && idx < items.length - 1) ul.insertBefore(li, items[idx+2] || null);
      }
    });
  });
});

async function addItemInline(form) {
  const pid = form.dataset.pid;
  const fd = new FormData(form);
  const r = await fetch(`/place/${pid}/add_item`, { method:'POST', body: fd });
  if (r.ok) {
    window.location.reload();
  } else {
    alert('Kunne ikke tilføje udstyr');
  }
  return false;
}


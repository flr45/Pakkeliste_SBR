
async function postJSON(url, data) {
  const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data||{}) });
  if (!res.ok) throw new Error(await res.text());
  return res.json().catch(()=>({ok:true}));
}
function toast(m){const d=document.createElement('div');d.textContent=m;d.style.cssText='position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#1b2530;border:1px solid #2a3440;color:#eaf2ff;padding:10px 14px;border-radius:10px;z-index:9999';document.body.appendChild(d);setTimeout(()=>d.remove(),1600);}

function makePlaceEditable(span){
  span.contentEditable="true";
  span.addEventListener('blur', async ()=>{
    const id=span.dataset.placeId, name=span.textContent.trim();
    if(!name){toast('Navn kan ikke være tomt'); return;}
    try{ await postJSON(`/place/${id}/rename`, {name}); toast('Gemt'); }catch(e){ toast('Fejl'); }
  });
}

function bindLocalSearch(){
  const input=document.getElementById('local-search'); if(!input) return;
  input.addEventListener('input', ()=>{
    const q=input.value.toLowerCase().replace('-',' ');
    document.querySelectorAll('[data-item-name]').forEach(el=>{
      el.style.display = el.dataset.itemName.includes(q)?'':'none';
    });
    document.querySelectorAll('details.place').forEach(d=>{
      const any = Array.from(d.querySelectorAll('[data-item-name]')).some(el=>el.style.display!== 'none');
      d.open = any;
    });
  });
}

async function movePlace(placeId, dir, btn){
  btn.disabled=true;
  try{
    await postJSON(`/place/${placeId}/move`, {direction:dir});
    const card=document.getElementById(`place-${placeId}`);
    if(!card) return location.reload();
    const c=card.parentElement;
    if(dir==='up' && card.previousElementSibling){ c.insertBefore(card, card.previousElementSibling); }
    else if(dir==='down' && card.nextElementSibling){ c.insertBefore(card.nextElementSibling, card); }
  }catch(e){ toast('Kunne ikke flytte'); }
  finally{ btn.disabled=false; }
}

async function triggerPhotoUpload(itemId){
  const inp=document.createElement('input'); inp.type='file'; inp.accept='image/*';
  inp.onchange=async()=>{
    const f=inp.files[0]; if(!f) return;
    const fd=new FormData(); fd.append('photo', f);
    const res=await fetch(`/item/${itemId}/photo`, {method:'POST', body:fd});
    if(!res.ok){ toast('Upload fejlede'); return; }
    const icon=document.getElementById(`photo-icon-${itemId}`); if(icon) icon.style.visibility='visible';
    toast('Billede gemt');
  };
  inp.click();
}

document.addEventListener('DOMContentLoaded', ()=>{
  document.querySelectorAll('[data-place-title]').forEach(makePlaceEditable);
  bindLocalSearch();
});

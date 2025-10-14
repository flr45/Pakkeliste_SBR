
const $ = (q,root=document)=>root.querySelector(q);
const $$ = (q,root=document)=>Array.from(root.querySelectorAll(q));
function initVehiclePage(){
  const params = new URLSearchParams(location.search);
  const openPlace = params.get('open_place');
  const highlightItem = params.get('highlight_item');
  if(openPlace){
    const el = document.getElementById('place-'+openPlace);
    if(el){ el.open = true; el.scrollIntoView({behavior:'smooth',block:'start'}); }
  }
  if(highlightItem){
    const it = document.getElementById('item-'+highlightItem);
    if(it){ it.classList.add('pulse'); it.scrollIntoView({behavior:'smooth',block:'center'}); setTimeout(()=>it.classList.remove('pulse'),2500); }
  }
  const q = $('#q-vehicle');
  if(q){
    q.addEventListener('input', ()=>{
      const term = q.value.toLowerCase().trim();
      $$('.place').forEach(p=>{
        let any=false;
        $$('.item',p).forEach(li=>{
          const text = li.dataset.search || li.innerText.toLowerCase();
          const show = !term || text.includes(term);
          li.style.display = show? 'block':'none';
          if(show) any=true;
        });
        p.style.display = any? 'block':'none';
      });
    });
  }
}
document.addEventListener('DOMContentLoaded', ()=>{
  if(document.body.dataset.page === 'vehicle'){ initVehiclePage(); }
});

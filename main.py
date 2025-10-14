
import os, csv, secrets, pathlib, shutil
from typing import Optional, List

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import create_engine, select, func, ForeignKey, String, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

os.makedirs("data", exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
templates = Jinja2Templates(directory="templates")

class Base(DeclarativeBase): pass

class Vehicle(Base):
    __tablename__="vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    places: Mapped[List["Place"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan", order_by="Place.sort")
    docs: Mapped[List["VehicleDoc"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan")

class Place(Base):
    __tablename__="places"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    vehicle: Mapped[Vehicle] = relationship(back_populates="places")
    items: Mapped[List["Item"]] = relationship(back_populates="place", cascade="all, delete-orphan", order_by="Item.sort")

class Item(Base):
    __tablename__="items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Optional[str]] = mapped_column(String(50), default=None)
    note: Mapped[Optional[str]] = mapped_column(String(400), default=None)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    photo_path: Mapped[Optional[str]] = mapped_column(String(400), default=None)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"))
    place: Mapped["Place"] = relationship(back_populates="items")

class VehicleDoc(Base):
    __tablename__="vehicle_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    original_name: Mapped[str] = mapped_column(String(300))
    stored_name: Mapped[str] = mapped_column(String(400))
    vehicle: Mapped["Vehicle"] = relationship(back_populates="docs")

engine = create_engine(DATABASE_URL, echo=False, future=True)
Base.metadata.create_all(engine)

def is_logged(request: Request)->bool: return bool(request.session.get("logged"))
def require_login(request: Request): return RedirectResponse("/login", status_code=303)

def normalize(s:str)->str: return (s or "").lower().replace("-"," ")

def save_upload(f: UploadFile, subdir:str="")->str:
    ext = pathlib.Path(f.filename).suffix
    safe = secrets.token_hex(8) + ext
    target_dir = pathlib.Path(UPLOAD_DIR) / subdir if subdir else pathlib.Path(UPLOAD_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe
    with open(target, "wb") as out:
        shutil.copyfileobj(f.file, out)
    # return path relative to base upload dir
    rel = target.relative_to(UPLOAD_DIR)
    return str(rel)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with Session(engine) as s:
        vrows = s.execute(
            select(Vehicle.id, Vehicle.name, Vehicle.description, func.count(Place.id))
            .join(Place, Place.vehicle_id == Vehicle.id, isouter=True)
            .group_by(Vehicle.id)
            .order_by(Vehicle.sort, Vehicle.name)
        ).all()
        vehicles = [dict(id=i, name=n, description=d, place_count=c) for (i,n,d,c) in vrows]
    return templates.TemplateResponse("index.html", {"request":request, "vehicles":vehicles, "logged":is_logged(request)})

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request":request, "logged":is_logged(request)})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == os.getenv("ADMIN_USERNAME","admin") and password == os.getenv("ADMIN_PASSWORD","admin"):
        request.session["logged"] = True
        return RedirectResponse("/?msg=Logget%20ind", status_code=303)
    return templates.TemplateResponse("login.html", {"request":request, "error":"Forkert login", "logged":False})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/?msg=Logget%20ud", status_code=303)

@app.get("/vehicles", response_class=HTMLResponse)
def vehicles_page(request: Request):
    with Session(engine) as s:
        rows = s.execute(select(Vehicle).order_by(Vehicle.sort, Vehicle.name)).scalars().all()
    return templates.TemplateResponse("index.html", {"request":request, "vehicles":[{"id":v.id,"name":v.name,"description":v.description,"place_count":len(v.places)} for v in rows], "logged":is_logged(request)})

@app.post("/vehicle/add")
def vehicle_add(request: Request, name: str = Form(...)):
    if not is_logged(request): return require_login(request)
    with Session(engine) as s:
        max_sort = s.scalar(select(func.coalesce(func.max(Vehicle.sort), 0))) or 0
        v = Vehicle(name=name.strip(), sort=max_sort+1)
        s.add(v); s.commit()
        return RedirectResponse(f"/vehicle/{v.id}", status_code=303)

@app.post("/vehicle/{vid}/delete")
def vehicle_delete(request: Request, vid: int):
    if not is_logged(request): return require_login(request)
    with Session(engine) as s:
        v = s.get(Vehicle, vid)
        if v: s.delete(v); s.commit()
    return RedirectResponse("/?msg=Køretøj%20slettes", status_code=303)

@app.get("/vehicle/{vid}", response_class=HTMLResponse)
def vehicle_detail(request: Request, vid: int):
    with Session(engine) as s:
        v = s.get(Vehicle, vid)
        if not v: return RedirectResponse("/", status_code=303)
        places = s.execute(select(Place).where(Place.vehicle_id == vid).order_by(Place.sort, Place.name)).scalars().all()
        items_by_place = {}
        for p in places:
            items_by_place[p.id] = s.execute(select(Item).where(Item.place_id == p.id).order_by(Item.sort, Item.name)).scalars().all()
        docs = s.execute(select(VehicleDoc).where(VehicleDoc.vehicle_id == vid)).scalars().all()
        data = {
            "id": v.id, "name": v.name, "description": v.description,
            "docs": [{"id":d.id, "original_name":d.original_name, "url": f"/uploads/{d.stored_name}"} for d in docs],
            "places": [{
                "id": p.id, "name": p.name,
                "items": [{"id":it.id,"name":it.name,"quantity":it.quantity,"note":it.note,"photo_path":it.photo_path} for it in items_by_place[p.id]]
            } for p in places]
        }
    return templates.TemplateResponse("vehicle.html", {"request":request, "v":data, "logged":is_logged(request)})

@app.post("/vehicle/{vid}/description")
def vehicle_set_description(request: Request, vid: int, description: str = Form("")):
    if not is_logged(request): return require_login(request)
    with Session(engine) as s:
        v = s.get(Vehicle, vid)
        if v:
            v.description = description.strip() or None
            s.commit()
    return RedirectResponse(f"/vehicle/{vid}", status_code=303)

@app.post("/vehicle/{vid}/doc")
def vehicle_add_doc(request: Request, vid: int, doc: UploadFile = File(...)):
    if not is_logged(request): return require_login(request)
    stored = save_upload(doc, subdir="docs")
    with Session(engine) as s:
        s.add(VehicleDoc(vehicle_id=vid, original_name=doc.filename, stored_name=stored))
        s.commit()
    return RedirectResponse(f"/vehicle/{vid}", status_code=303)

@app.post("/place/add")
def place_add(request: Request, vehicle_id: int = Form(...), name: str = Form(...)):
    if not is_logged(request): return require_login(request)
    with Session(engine) as s:
        max_sort = s.scalar(select(func.coalesce(func.max(Place.sort), 0)).where(Place.vehicle_id == vehicle_id)) or 0
        p = Place(vehicle_id=vehicle_id, name=name.strip(), sort=max_sort+1)
        s.add(p); s.commit()
        return RedirectResponse(f"/vehicle/{vehicle_id}", status_code=303)

@app.post("/place/{pid}/rename")
def place_rename(request: Request, pid: int, payload: dict):
    if not is_logged(request): return JSONResponse({"ok": False}, status_code=403)
    name = (payload or {}).get("name","").strip()
    if not name: return JSONResponse({"ok": False}, status_code=400)
    with Session(engine) as s:
        p = s.get(Place, pid)
        if not p: return JSONResponse({"ok": False}, status_code=404)
        p.name = name; s.commit()
    return JSONResponse({"ok": True})

@app.post("/place/{pid}/move")
def place_move(request: Request, pid: int, payload: dict):
    if not is_logged(request): return JSONResponse({"ok": False}, status_code=403)
    direction = (payload or {}).get("direction")
    with Session(engine) as s:
        p = s.get(Place, pid)
        if not p: return JSONResponse({"ok": False}, status_code=404)
        siblings = s.execute(select(Place).where(Place.vehicle_id == p.vehicle_id).order_by(Place.sort, Place.id)).scalars().all()
        idx = siblings.index(p)
        if direction == "up" and idx > 0:
            siblings[idx].sort, siblings[idx-1].sort = siblings[idx-1].sort, siblings[idx].sort
        elif direction == "down" and idx < len(siblings)-1:
            siblings[idx].sort, siblings[idx+1].sort = siblings[idx+1].sort, siblings[idx].sort
        s.commit()
    return JSONResponse({"ok": True})

@app.post("/item/add")
def item_add(request: Request, place_id: int = Form(...), name: str = Form(...), quantity: str = Form(""), note: str = Form("")):
    if not is_logged(request): return require_login(request)
    with Session(engine) as s:
        max_sort = s.scalar(select(func.coalesce(func.max(Item.sort), 0)).where(Item.place_id == place_id)) or 0
        it = Item(place_id=place_id, name=name.strip(), quantity=(quantity or None), note=(note or None), sort=max_sort+1)
        s.add(it); s.commit()
        vid = s.scalar(select(Place.vehicle_id).where(Place.id == place_id))
        return RedirectResponse(f"/vehicle/{vid}", status_code=303)

@app.post("/item/{iid}/save")
def item_save(request: Request, iid: int, name: str = Form(...), quantity: str = Form(""), note: str = Form("")):
    if not is_logged(request): return require_login(request)
    with Session(engine) as s:
        it = s.get(Item, iid)
        if it:
            it.name = name.strip(); it.quantity = quantity or None; it.note = note or None; s.commit()
            vid = s.scalar(select(Place.vehicle_id).where(Place.id == it.place_id))
            return RedirectResponse(f"/vehicle/{vid}", status_code=303)
    return RedirectResponse("/", status_code=303)

@app.post("/item/{iid}/delete")
def item_delete(request: Request, iid: int):
    if not is_logged(request): return require_login(request)
    with Session(engine) as s:
        it = s.get(Item, iid)
        if it:
            vid = s.scalar(select(Place.vehicle_id).where(Place.id == it.place_id))
            s.delete(it); s.commit()
            return RedirectResponse(f"/vehicle/{vid}", status_code=303)
    return RedirectResponse("/", status_code=303)

@app.post("/item/{iid}/photo")
def item_photo(request: Request, iid: int, photo: UploadFile = File(...)):
    if not is_logged(request): return JSONResponse({"ok": False}, status_code=403)
    stored = save_upload(photo, subdir="items")
    with Session(engine) as s:
        it = s.get(Item, iid)
        if not it: return JSONResponse({"ok": False}, status_code=404)
        it.photo_path = stored; s.commit()
    return JSONResponse({"ok": True, "path": f"/uploads/{stored}"})

@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", vehicle: int = 0):
    qn = normalize(q)
    with Session(engine) as s:
        stmt = select(
            Item.id.label("item_id"), Item.name.label("item_name"), Item.photo_path,
            Place.name.label("place_name"), Vehicle.name.label("vehicle_name"), Vehicle.id.label("vehicle_id")
        ).join(Place, Place.id == Item.place_id).join(Vehicle, Vehicle.id == Place.vehicle_id)
        if vehicle and str(vehicle).isdigit():
            stmt = stmt.where(Vehicle.id == int(vehicle))
        if qn:
            like = f"%{qn}%"
            stmt = stmt.where(func.lower(func.replace(Item.name, "-", " ")).like(like))
        rows = s.execute(stmt.order_by(Vehicle.name, Place.name, Item.name)).all()
        results = [dict(item_id=r.item_id, item_name=r.item_name, photo_path=r.photo_path, place_name=r.place_name, vehicle_name=r.vehicle_name, vehicle_id=r.vehicle_id) for r in rows]
        vehicles = s.execute(select(Vehicle).order_by(Vehicle.name)).scalars().all()
    return templates.TemplateResponse("search.html", {"request":request, "q":q, "results":results, "vehicles":vehicles, "vehicle_filter": int(vehicle) if str(vehicle).isdigit() else 0, "logged":is_logged(request)})

@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    if not is_logged(request): return require_login(request)
    return templates.TemplateResponse("upload.html", {"request":request, "logged":True})

@app.post("/upload")
def upload_csv(request: Request, file: UploadFile = File(...)):
    if not is_logged(request): return require_login(request)
    content = file.file.read().decode("utf-8", errors="ignore")
    import csv
    rdr = csv.reader(content.splitlines())
    header = next(rdr, None)
    if not header: return HTMLResponse("Tom fil", status_code=400)
    header = [h.strip() for h in header]
    expected1 = ["Brandbil","Rum/Låge","Udstyr","Antal","Note"]
    expected2 = ["Rum/Låge","Udstyr","Antal","Note"]
    has_vehicle = False
    if header == expected1: has_vehicle = True
    elif header != expected2:
        return HTMLResponse("Import fejl: Forkert header.", status_code=400)

    from sqlalchemy import select
    with Session(engine) as s:
        v_cache = {}; p_cache = {}
        for row in rdr:
            if not row or all(not (c or '').strip() for c in row): continue
            if has_vehicle:
                vehicle_name, place_name, item_name, qty, note = [c.strip() for c in (row+['']*5)[:5]]
            else:
                place_name, item_name, qty, note = [c.strip() for c in (row+['']*4)[:4]]
                vehicle_name = "Uden navn"
            if vehicle_name not in v_cache:
                v = s.execute(select(Vehicle).where(Vehicle.name==vehicle_name)).scalar_one_or_none()
                if not v:
                    maxs = s.scalar(select(func.coalesce(func.max(Vehicle.sort),0))) or 0
                    v = Vehicle(name=vehicle_name, sort=maxs+1); s.add(v); s.flush()
                v_cache[vehicle_name] = v.id
            vid = v_cache[vehicle_name]
            keyp = (vid, place_name)
            if keyp not in p_cache:
                p = s.execute(select(Place).where(Place.vehicle_id==vid, Place.name==place_name)).scalar_one_or_none()
                if not p:
                    maxp = s.scalar(select(func.coalesce(func.max(Place.sort),0)).where(Place.vehicle_id==vid)) or 0
                    p = Place(vehicle_id=vid, name=place_name, sort=maxp+1); s.add(p); s.flush()
                p_cache[keyp] = p.id
            pid = p_cache[keyp]
            maxit = s.scalar(select(func.coalesce(func.max(Item.sort),0)).where(Item.place_id==pid)) or 0
            it = Item(place_id=pid, name=item_name, quantity=(qty or None), note=(note or None), sort=maxit+1)
            s.add(it)
        s.commit()
    return RedirectResponse("/?msg=Import%20ok", status_code=303)

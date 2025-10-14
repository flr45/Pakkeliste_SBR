
import os
from typing import Optional, List, Dict

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import create_engine, select, func, text, Column, Integer, String, ForeignKey
from sqlalchemy.orm import Session, sessionmaker, declarative_base, relationship, joinedload, selectinload

# ------------------ Config ------------------
DB_PATH = os.environ.get("DB_PATH", "app.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin")

app = FastAPI()

# Ensure uploads dir exists on boot
os.makedirs('uploads', exist_ok=True)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

engine = create_engine(f"sqlite:///{DB_PATH}", future=True, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()

# ------------------ Models ------------------

class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    sort = Column(Integer, default=0, nullable=False)
    description = Column(String, default="", nullable=False)

    places = relationship(
        "Place",
        back_populates="vehicle",
        cascade="all, delete-orphan",
        order_by="Place.sort",
    )

class Place(Base):
    __tablename__ = "places"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sort = Column(Integer, default=0, nullable=False)

    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    vehicle = relationship("Vehicle", back_populates="places")

    items = relationship(
        "Item",
        back_populates="place",
        cascade="all, delete-orphan",
        order_by="Item.sort",
    )

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    note = Column(String, default="", nullable=False)
    sort = Column(Integer, default=0, nullable=False)
    photo_path = Column(String, nullable=True)

    place_id = Column(Integer, ForeignKey("places.id"), nullable=False, index=True)
    place = relationship("Place", back_populates="items")

# ------------------ DB bootstrapping ------------------

def ensure_columns(engine):
    # add missing columns for existing dbs
    with engine.begin() as conn:
        # vehicles
        vcols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(vehicles)").fetchall()]
        if "sort" not in vcols:
            conn.exec_driver_sql("ALTER TABLE vehicles ADD COLUMN sort INTEGER DEFAULT 0")
        if "description" not in vcols:
            conn.exec_driver_sql("ALTER TABLE vehicles ADD COLUMN description TEXT DEFAULT ''")

        # places
        pcols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(places)").fetchall()]
        if "sort" not in pcols:
            conn.exec_driver_sql("ALTER TABLE places ADD COLUMN sort INTEGER DEFAULT 0")
        if "vehicle_id" not in pcols:
            conn.exec_driver_sql("ALTER TABLE places ADD COLUMN vehicle_id INTEGER")
            vid = conn.execute(text("SELECT id FROM vehicles ORDER BY id LIMIT 1")).scalar()
            if vid is None:
                conn.exec_driver_sql("INSERT INTO vehicles (name, sort, description) VALUES ('Ukendt', 0, '')")
                vid = conn.execute(text("SELECT id FROM vehicles ORDER BY id LIMIT 1")).scalar()
            conn.execute(text("UPDATE places SET vehicle_id = :vid WHERE vehicle_id IS NULL"), {"vid": vid})
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_places_vehicle_id ON places(vehicle_id)")

        # items
        icols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(items)").fetchall()]
        if "quantity" not in icols:
            conn.exec_driver_sql("ALTER TABLE items ADD COLUMN quantity INTEGER DEFAULT 1")
        if "sort" not in icols:
            conn.exec_driver_sql("ALTER TABLE items ADD COLUMN sort INTEGER DEFAULT 0")
        if "photo_path" not in icols:
            conn.exec_driver_sql("ALTER TABLE items ADD COLUMN photo_path TEXT")
        if "place_id" not in icols:
            conn.exec_driver_sql("ALTER TABLE items ADD COLUMN place_id INTEGER")
            # Fallback place
            pid = conn.execute(text("SELECT id FROM places ORDER BY id LIMIT 1")).scalar()
            if pid is None:
                vid = conn.execute(text("SELECT id FROM vehicles ORDER BY id LIMIT 1")).scalar()
                if vid is None:
                    conn.exec_driver_sql("INSERT INTO vehicles (name, sort, description) VALUES ('Ukendt', 0, '')")
                    vid = conn.execute(text("SELECT id FROM vehicles ORDER BY id LIMIT 1")).scalar()
                conn.exec_driver_sql("INSERT INTO places (name, sort, vehicle_id) VALUES ('Ukendt rum', 0, ?)", (vid,))
                pid = conn.execute(text("SELECT id FROM places ORDER BY id LIMIT 1")).scalar()
            conn.execute(text("UPDATE items SET place_id = :pid WHERE place_id IS NULL"), {"pid": pid})
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_items_place_id ON items(place_id)")

Base.metadata.create_all(engine)
ensure_columns(engine)

# ------------------ Helpers ------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user"))

def require_login(request: Request):
    if not is_logged_in(request):
        return RedirectResponse("/login?next=" + request.url.path, status_code=303)

def norm(s: str) -> str:
    # Normaliser søgetermer: fjern bindestreger/underscores, komprimer whitespace, lower-case
    return "".join(ch for ch in s.lower().strip() if ch.isalnum() or ch.isspace())

# ------------------ Routes ------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    vehicles = db.execute(select(Vehicle).order_by(Vehicle.sort, Vehicle.name)).scalars().all()
    # Precompute place_counts
    place_counts: Dict[int, int] = {}
    for v in vehicles:
        for p in v.places:
            place_counts[p.id] = db.scalar(select(func.count(Item.id)).where(Item.place_id == p.id)) or 0
    return templates.TemplateResponse("index.html", {
        "request": request,
        "vehicles": vehicles,
        "place_counts": place_counts,
        "logged": is_logged_in(request),
        "msg": request.query_params.get("msg", "")
    })

# ---- Auth ----

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "msg": request.query_params.get("msg","")})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/", alias="next")):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = username
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "msg":"Forkert login"})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/?msg=Logget ud", status_code=303)

# ---- Vehicles CRUD ----

@app.get("/vehicles", response_class=HTMLResponse)
def vehicle_list(request: Request, db: Session = Depends(get_db)):
    vehicles = db.execute(select(Vehicle).order_by(Vehicle.sort, Vehicle.name)).scalars().all()
    return templates.TemplateResponse("vehicles.html", {"request":request, "vehicles":vehicles, "logged":is_logged_in(request)})

@app.post("/vehicles")
def vehicle_create(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    v = Vehicle(name=name.strip())
    db.add(v)
    db.commit()
    return RedirectResponse("/vehicles", status_code=303)

@app.post("/vehicle/{vehicle_id}/delete")
def vehicle_delete(request: Request, vehicle_id: int, db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    v = db.get(Vehicle, vehicle_id)
    if v:
        db.delete(v)
        db.commit()
    return RedirectResponse("/?msg=Køretøj slettet", status_code=303)

# ---- Vehicle detail & Places/Items ----

@app.get("/vehicle/{vehicle_id}", response_class=HTMLResponse)
def vehicle_detail(request: Request, vehicle_id: int, db: Session = Depends(get_db)):
    # eager load places and items (ordered by sort)
    v: Optional[Vehicle] = db.execute(
        select(Vehicle)
        .options(joinedload(Vehicle.places).joinedload(Place.items))
        .where(Vehicle.id == vehicle_id)
    ).scalars().first()
    if not v:
        return RedirectResponse("/?msg=Køretøj findes ikke", status_code=303)

    # precompute place_counts
    place_counts = {p.id: len(p.items) for p in v.places}
    return templates.TemplateResponse("vehicle.html", {
        "request": request, "v": v, "place_counts": place_counts, "logged": is_logged_in(request)
    })

@app.post("/vehicle/{vehicle_id}/place/add")
def place_add(request: Request, vehicle_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    v = db.get(Vehicle, vehicle_id)
    if not v:
        return RedirectResponse("/?msg=Køretøj findes ikke", status_code=303)
    max_sort = db.scalar(select(func.coalesce(func.max(Place.sort), 0)).where(Place.vehicle_id == vehicle_id)) or 0
    p = Place(name=name.strip(), vehicle_id=vehicle_id, sort=max_sort+1)
    db.add(p)
    db.commit()
    return RedirectResponse(f"/vehicle/{vehicle_id}", status_code=303)

@app.post("/place/{place_id}/rename")
def place_rename(request: Request, place_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    p = db.get(Place, place_id)
    if p:
        p.name = name.strip()
        db.commit()
        return RedirectResponse(f"/vehicle/{p.vehicle_id}", status_code=303)
    return RedirectResponse("/", status_code=303)

@app.post("/place/{place_id}/move")
def place_move(request: Request, place_id: int, direction: str = Form(...), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    p = db.get(Place, place_id)
    if not p:
        return RedirectResponse("/", status_code=303)
    delta = -1 if direction == "up" else 1
    neighbor = db.execute(
        select(Place).where(Place.vehicle_id == p.vehicle_id, Place.sort == p.sort + delta)
    ).scalars().first()
    if neighbor:
        neighbor.sort, p.sort = p.sort, neighbor.sort
        db.commit()
    return RedirectResponse(f"/vehicle/{p.vehicle_id}", status_code=303)

@app.post("/item/add")
def item_add(request: Request, place_id: int = Form(...), name: str = Form(...), quantity: int = Form(1), note: str = Form(""), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    max_sort = db.scalar(select(func.coalesce(func.max(Item.sort), 0)).where(Item.place_id == place_id)) or 0
    it = Item(place_id=place_id, name=name.strip(), quantity=quantity, note=note.strip(), sort=max_sort+1)
    db.add(it)
    db.commit()
    v_id = db.scalar(select(Place.vehicle_id).where(Place.id == place_id))
    return RedirectResponse(f"/vehicle/{v_id}", status_code=303)

@app.post("/item/{item_id}/edit")
def item_edit(request: Request, item_id: int, name: str = Form(...), quantity: int = Form(1), note: str = Form(""), place_id: int = Form(...), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    it = db.get(Item, item_id)
    if it:
        it.name = name.strip()
        it.quantity = quantity
        it.note = note.strip()
        # flyt mellem kasser
        it.place_id = place_id
        db.commit()
        v_id = db.scalar(select(Place.vehicle_id).where(Place.id == it.place_id))
        return RedirectResponse(f"/vehicle/{v_id}", status_code=303)
    return RedirectResponse("/", status_code=303)

@app.post("/item/{item_id}/move")
def item_move(request: Request, item_id: int, direction: str = Form(...), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    it = db.get(Item, item_id)
    if not it:
        return RedirectResponse("/", status_code=303)
    delta = -1 if direction == "up" else 1
    neighbor = db.execute(
        select(Item).where(Item.place_id == it.place_id, Item.sort == it.sort + delta)
    ).scalars().first()
    if neighbor:
        neighbor.sort, it.sort = it.sort, neighbor.sort
        db.commit()
    v_id = db.scalar(select(Place.vehicle_id).where(Place.id == it.place_id))
    return RedirectResponse(f"/vehicle/{v_id}", status_code=303)

@app.post("/item/{item_id}/delete")
def item_delete(request: Request, item_id: int, db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    it = db.get(Item, item_id)
    if it:
        v_id = db.scalar(select(Place.vehicle_id).where(Place.id == it.place_id))
        db.delete(it)
        db.commit()
        return RedirectResponse(f"/vehicle/{v_id}", status_code=303)
    return RedirectResponse("/", status_code=303)

# ---- Upload CSV ----

@app.get("/import", response_class=HTMLResponse)
def import_form(request: Request):
    return templates.TemplateResponse("import.html", {"request":request, "logged":is_logged_in(request), "msg": request.query_params.get("msg","")})

@app.post("/import")
async def import_csv(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not is_logged_in(request):
        return require_login(request)
    import csv, io
    content = await file.read()
    text_data = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text_data), delimiter=",")
    rows = list(reader)
    if not rows:
        return RedirectResponse("/import?msg=Tom fil", status_code=303)

    header = [h.strip().lower() for h in rows[0]]
    # to header variants
    expected1 = ["brandbil","rum/låge","udstyr","antal","note"]
    expected2 = ["rum/låge","udstyr","antal","note"]

    start_idx = 1
    vehicle_name = None
    if header == expected1:
        vehicle_name = rows[1][0].strip()
        start_idx = 1
    elif header == expected2:
        vehicle_name = "Import " + os.path.splitext(file.filename)[0]
        start_idx = 1
    else:
        return RedirectResponse("/import?msg=Forkert header. Forventede 'Brandbil,Rum/Låge,Udstyr,Antal,Note' eller 'Rum/Låge,Udstyr,Antal,Note'.", status_code=303)

    # find or create vehicle
    v = db.execute(select(Vehicle).where(func.lower(Vehicle.name) == vehicle_name.lower())).scalars().first()
    if not v:
        v = Vehicle(name=vehicle_name)
        db.add(v)
        db.commit()
        db.refresh(v)

    # clear existing places/items on that vehicle
    for p in list(v.places):
        db.delete(p)
    db.commit()

    # group by place name
    place_map: Dict[str, Place] = {}
    for r in rows[start_idx:]:
        if not r or len(r) < len(header):
            continue
        # map fields
        if header == expected1:
            place_name, item_name, qty, note = r[1].strip(), r[2].strip(), r[3].strip() or "1", (r[4].strip() if len(r) > 4 else "")
        else:
            place_name, item_name, qty, note = r[0].strip(), r[1].strip(), r[2].strip() or "1", (r[3].strip() if len(r) > 3 else "")

        if not place_name:
            place_name = "Ukendt"
        if place_name not in place_map:
            max_sort = db.scalar(select(func.coalesce(func.max(Place.sort), 0)).where(Place.vehicle_id == v.id)) or 0
            p = Place(name=place_name, vehicle_id=v.id, sort=max_sort+1)
            db.add(p)
            db.commit()
            db.refresh(p)
            place_map[place_name] = p
        else:
            p = place_map[place_name]

        try:
            qty_int = int(qty)
        except:
            qty_int = 1
        max_isort = db.scalar(select(func.coalesce(func.max(Item.sort), 0)).where(Item.place_id == p.id)) or 0
        it = Item(place_id=p.id, name=item_name, quantity=qty_int, note=note, sort=max_isort+1)
        db.add(it)
        db.commit()

    return RedirectResponse(f"/vehicle/{v.id}?msg=Import OK", status_code=303)

# ---- Search ----

@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", vehicle: int = 0, db: Session = Depends(get_db)):
    qn = norm(q)
    vehicles = db.execute(select(Vehicle).order_by(Vehicle.sort, Vehicle.name)).scalars().all()
    rows = []
    if qn:
        stmt = (
            select(Item, Place, Vehicle)
            .join(Place, Item.place_id == Place.id)
            .join(Vehicle, Place.vehicle_id == Vehicle.id)
            .order_by(Vehicle.name, Place.name, Item.name)
        )
        results = db.execute(stmt).all()
        # Filter in Python to support our normalization and token search
        tokens = [t for t in qn.split() if t]
        for it, pl, ve in results:
            hay = norm(it.name) + " " + norm(pl.name) + " " + norm(ve.name)
            if all(t in hay for t in tokens):
                rows.append((it, pl, ve))

        # deduplicate by item id+place id (avoid double if eager loads)
        seen = set()
        unique = []
        for it, pl, ve in rows:
            key = (it.id, pl.id)
            if key not in seen:
                seen.add(key)
                unique.append((it, pl, ve))
        rows = unique

        # vehicle filter
        if vehicle and str(vehicle).isdigit():
            rows = [r for r in rows if r[2].id == int(vehicle)]
    return templates.TemplateResponse("search.html", {
        "request": request, "rows": rows, "q": q, "vehicle": vehicle, "vehicles": vehicles, "logged": is_logged_in(request)
    })

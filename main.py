import os, io, csv, secrets
from typing import Optional, List

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware  # <— rettet her
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session, selectinload
from sqlalchemy import Integer, String, ForeignKey, Text

# ----------------------- Config -----------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
SECRET_KEY   = os.getenv("APP_SECRET", "change-me")
ADMIN_USER   = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS   = os.getenv("ADMIN_PASS", "admin")

os.makedirs("uploads/items", exist_ok=True)
os.makedirs("uploads/docs", exist_ok=True)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="pl_sess", max_age=60*60*12)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

# ----------------------- DB Models -----------------------
class Base(DeclarativeBase): pass

class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    places: Mapped[List["Place"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan", order_by="Place.sort, Place.name")
    docs: Mapped[List["VehicleDoc"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan", order_by="VehicleDoc.id")

class VehicleDoc(Base):
    __tablename__ = "vehicle_docs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(400))
    vehicle: Mapped["Vehicle"] = relationship(back_populates="docs")

class Place(Base):
    __tablename__ = "places"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    vehicle: Mapped["Vehicle"] = relationship(back_populates="places")
    items: Mapped[List["Item"]] = relationship(back_populates="place", cascade="all, delete-orphan", order_by="Item.sort, Item.name")

class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[Optional[str]] = mapped_column(String(500), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    photo_path: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), index=True)
    place: Mapped["Place"] = relationship(back_populates="items")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
Base.metadata.create_all(engine)

def db() -> Session: return Session(engine)
def is_logged(req: Request) -> bool: return bool(req.session.get("user"))
def require_login(req: Request):
    from fastapi import HTTPException
    if not is_logged(req):
        # Safe redirect via raising response
        raise RedirectResponse("/login", status_code=303)

# ----------------------- Auth -----------------------
@app.get("/login")
def login_form(request: Request, msg: Optional[str]=None):
    return templates.TemplateResponse("login.html", {"request":request, "msg":msg})

@app.post("/login")
def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = username
        return RedirectResponse("/", 303)
    return templates.TemplateResponse("login.html", {"request":request, "msg":"Forkert login"})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)

# ----------------------- Pages -----------------------
@app.get("/")
def home(request: Request):
    with db() as s:
        rows = s.execute(select(Vehicle).order_by(Vehicle.sort, Vehicle.name)).scalars().all()
        vehicles = [{"id":v.id,"name":v.name} for v in rows]
    return templates.TemplateResponse("index.html", {"request":request, "vehicles":vehicles, "logged":is_logged(request)})

@app.post("/vehicles/new")
def create_vehicle(request: Request, name: str = Form(...), description: str = Form("")):
    require_login(request)
    with db() as s:
        if s.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.name==name))>0:
            return RedirectResponse("/?msg=Findes%20allerede", 303)
        v = Vehicle(name=name.strip(), description=description.strip())
        s.add(v); s.commit()
        return RedirectResponse(f"/vehicle/{v.id}", 303)

@app.get("/vehicle/{vehicle_id}")
def vehicle_detail(request: Request, vehicle_id: int):
    with db() as s:
        v = s.execute(
            select(Vehicle)
            .options(
                selectinload(Vehicle.places).selectinload(Place.items),
                selectinload(Vehicle.docs)
            )
            .where(Vehicle.id==vehicle_id)
        ).scalar_one_or_none()
        if not v: return Response("Ikke fundet", status_code=404)
        data = {
            "id": v.id, "name": v.name, "description": v.description or "",
            "docs": [{"id":d.id,"filename":d.filename,"path":d.path} for d in v.docs],
            "places":[
                {"id":p.id,"name":p.name,"items":[
                    {"id":it.id,"name":it.name,"quantity":it.quantity,"note":it.note or "","photo_path":it.photo_path}
                for it in p.items]}
            for p in v.places]
        }
    return templates.TemplateResponse("vehicle.html", {"request":request, "v":data, "logged":is_logged(request)})

# ----------------------- Inline edits & adds (AJAX) -----------------------
@app.post("/vehicle/{vehicle_id}/description")
def update_vehicle_description(request: Request, vehicle_id:int, description: str = Form("")):
    require_login(request)
    with db() as s:
        v = s.get(Vehicle, vehicle_id)
        if not v: return JSONResponse({"ok":False}, status_code=404)
        v.description = description.strip()
        s.commit()
    return JSONResponse({"ok":True})

@app.post("/vehicle/{vehicle_id}/places/new")
def create_place(request: Request, vehicle_id:int, name: str = Form(...)):
    require_login(request)
    with db() as s:
        v = s.get(Vehicle, vehicle_id)
        if not v: return JSONResponse({"ok":False}, status_code=404)
        p = Place(name=name.strip(), vehicle=v)
        s.add(p); s.commit()
        return JSONResponse({"ok":True, "id":p.id, "name":p.name})

@app.post("/place/{place_id}/rename")
def rename_place(request: Request, place_id:int, name: str = Form(...)):
    require_login(request)
    with db() as s:
        p = s.get(Place, place_id)
        if not p: return JSONResponse({"ok":False}, status_code=404)
        p.name = name.strip()
        s.commit()
        return JSONResponse({"ok":True})

@app.post("/place/{place_id}/items/new")
def create_item(request: Request, place_id:int, name: str = Form(...), quantity:int = Form(1), note:str = Form("")):
    require_login(request)
    with db() as s:
        p = s.get(Place, place_id)
        if not p: return JSONResponse({"ok":False}, status_code=404)
        it = Item(name=name.strip(), quantity=int(quantity or 1), note=note.strip(), place=p)
        s.add(it); s.commit()
        return JSONResponse({"ok":True, "id":it.id})

@app.post("/item/{item_id}/photo")
async def upload_item_photo(request: Request, item_id:int, file: UploadFile = File(...)):
    require_login(request)
    ext = os.path.splitext(file.filename)[1].lower()
    safe = secrets.token_hex(8) + ext
    path = f"uploads/items/{safe}"
    with open(path, "wb") as f: f.write(await file.read())
    with db() as s:
        it = s.get(Item, item_id)
        if not it: return JSONResponse({"ok":False}, status_code=404)
        it.photo_path = "/" + path
        s.commit()
    return JSONResponse({"ok":True, "path": "/" + path})

@app.post("/vehicle/{vehicle_id}/docs")
async def upload_vehicle_doc(request: Request, vehicle_id: int, file: UploadFile = File(...)):
    require_login(request)
    safe = secrets.token_hex(8) + "_" + file.filename.replace("/", "_")
    path = f"uploads/docs/{safe}"
    with open(path, "wb") as f: f.write(await file.read())
    with db() as s:
        v = s.get(Vehicle, vehicle_id)
        if not v: return JSONResponse({"ok":False}, status_code=404)
        d = VehicleDoc(vehicle=v, filename=file.filename, path="/" + path)
        s.add(d); s.commit()
        return JSONResponse({"ok":True, "id":d.id, "filename":d.filename, "path":d.path})

# ----------------------- Import / Export -----------------------
def _read_csv_bytes(b: bytes):
    try: text = b.decode("utf-8")
    except UnicodeDecodeError:
        try: text = b.decode("latin-1")
        except UnicodeDecodeError: text = b.decode(errors="ignore")
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = ";" if ";" in first else ("," if "," in first else ";")
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = []
    for row in reader:
        rows.append({(k or '').strip().lower(): (v.strip() if isinstance(v,str) else v) for k,v in row.items()})
    return rows

@app.get("/upload")
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request":request, "logged":is_logged(request)})

@app.post("/upload")
async def do_upload(request: Request, file: UploadFile = File(...)):
    require_login(request)
    rows = _read_csv_bytes(await file.read())
    with db() as s:
        veh_cache = {v.name.lower(): v for v in s.execute(select(Vehicle)).scalars().all()}
        for r in rows:
            vname = (r.get("vehicle") or r.get("køretøj") or "").strip()
            pname = (r.get("place") or r.get("rum") or r.get("kasse") or "").strip()
            iname = (r.get("item") or r.get("udstyr") or r.get("navn") or "").strip()
            qty = r.get("quantity") or r.get("antal") or "1"
            note = r.get("note") or r.get("bemærkning") or ""
            if not (pname and iname): continue
            veh = veh_cache.get(vname.lower()) if vname else None
            if not veh:
                key = vname.lower() if vname else "standard"
                veh = veh_cache.get(key)
                if not veh:
                    veh = Vehicle(name=vname or "Standard"); s.add(veh); s.flush(); veh_cache[key] = veh
            place = None
            for p in veh.places:
                if p.name.lower() == pname.lower(): place = p; break
            if not place:
                place = Place(name=pname, vehicle=veh); s.add(place); s.flush()
            try: q = int(str(qty) or "1")
            except: q = 1
            s.add(Item(name=iname, quantity=q, note=note, place=place))
        s.commit()
    return RedirectResponse("/?msg=Import%20ok", 303)

@app.get("/vehicle/{vehicle_id}/export")
def export_vehicle(vehicle_id: int):
    output = io.StringIO(); writer = csv.writer(output, delimiter=";")
    writer.writerow(["Vehicle","Place","Item","Quantity","Note"])
    with db() as s:
        v = s.execute(
            select(Vehicle)
            .options(selectinload(Vehicle.places).selectinload(Place.items))
            .where(Vehicle.id==vehicle_id)
        ).scalar_one_or_none()
        if not v: return Response(status_code=404)
        for p in v.places:
            for it in p.items:
                writer.writerow([v.name, p.name, it.name, it.quantity, it.note or ""])
    data = output.getvalue().encode("utf-8")
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{v.name}_pakkeliste.csv"'})

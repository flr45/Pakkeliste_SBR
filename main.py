
import os, csv, io, datetime
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session
from starlette.middleware.sessions import SessionMiddleware

os.makedirs("uploads/vehicle_docs", exist_ok=True)
os.makedirs("uploads/items", exist_ok=True)
os.makedirs("static", exist_ok=True)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY","dev-secret"))
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

class Base(DeclarativeBase): pass
engine = create_engine("sqlite:///data.db", echo=False)

class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    places: Mapped[list["Place"]] = relationship(back_populates="vehicle", order_by="Place.sort", cascade="all, delete-orphan")
    docs: Mapped[list["VehicleDoc"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan")

class Place(Base):
    __tablename__ = "places"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    vehicle: Mapped[Vehicle] = relationship(back_populates="places")
    items: Mapped[list["Item"]] = relationship(back_populates="place", order_by="Item.name", cascade="all, delete-orphan")

class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    photo_filename: Mapped[str | None] = mapped_column(String(255), default=None)
    place: Mapped[Place] = relationship(back_populates="items")

class VehicleDoc(Base):
    __tablename__ = "vehicle_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    orig_name: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[str] = mapped_column(String(32))
    vehicle: Mapped[Vehicle] = relationship(back_populates="docs")

Base.metadata.create_all(engine)

def is_logged(request: Request)->bool:
    return request.session.get("auth")==1

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with Session(engine) as s:
        rows = s.execute(select(Vehicle).order_by(Vehicle.sort, Vehicle.name)).scalars().all()
        data = [{"id":v.id,"name":v.name,"place_count":len(v.places)} for v in rows]
    return templates.TemplateResponse("index.html", {"request": request, "vehicles": data, "logged": is_logged(request)})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, msg: str | None = None):
    return templates.TemplateResponse("login.html", {"request":request, "msg":msg})

@app.post("/login")
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    u = os.getenv("ADMIN_USER","admin"); p = os.getenv("ADMIN_PASSWORD","admin")
    if username == u and password == p:
        request.session["auth"]=1; return RedirectResponse("/", status_code=303)
    return RedirectResponse("/login?msg=Forkert+login", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/", status_code=303)

@app.get("/search", response_class=HTMLResponse)
def global_search(request: Request, q: str | None = None):
    results = []
    if q:
        term = f"%{q.lower()}%"
        with Session(engine) as s:
            rows = s.execute(
                select(Item, Place, Vehicle)
                .join(Place, Item.place_id == Place.id)
                .join(Vehicle, Place.vehicle_id == Vehicle.id)
                .where((Item.name.ilike(term)) | (Item.note.ilike(term)))
                .order_by(Vehicle.name, Place.name, Item.name)
            ).all()
            for it, pl, ve in rows:
                results.append({
                    "vehicle_id": ve.id, "vehicle_name": ve.name,
                    "place_id": pl.id, "place_name": pl.name,
                    "item_id": it.id, "item_name": it.name, "quantity": it.quantity
                })
    return templates.TemplateResponse("search.html", {"request":request, "q":q, "results":results, "logged": is_logged(request)})

@app.get("/vehicle/{vehicle_id}", response_class=HTMLResponse)
def vehicle_detail(request: Request, vehicle_id: int):
    with Session(engine) as s:
        v = s.get(Vehicle, vehicle_id)
        if not v:
            return RedirectResponse("/", status_code=303)
        places = []
        for p in v.places:
            items = [{"id":i.id,"name":i.name,"quantity":i.quantity,"note":i.note,"photo_filename":i.photo_filename} for i in p.items]
            places.append({"id":p.id,"name":p.name,"items":items})
        docs = [{"id":d.id,"orig_name":d.orig_name} for d in v.docs]
        data = {"id":v.id,"name":v.name,"description":v.description,"places":places}
    return templates.TemplateResponse("vehicle.html", {"request":request, "v":data, "docs":docs, "logged":is_logged(request)})

@app.get("/vehicle/{vehicle_id}/export")
def export_vehicle(vehicle_id: int):
    with Session(engine) as s:
        v = s.get(Vehicle, vehicle_id)
        if not v: 
            return RedirectResponse("/", status_code=303)
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(["Køretøj","Rum","Udstyr","Antal","Note"])
        for p in v.places:
            for i in p.items:
                w.writerow([v.name, p.name, i.name, i.quantity, i.note or ""])
        output.seek(0)
        return StreamingResponse(iter([output.read()]), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{v.name}_pakkeliste.csv"'} )

@app.post("/vehicle/{vehicle_id}/description")
def set_description(vehicle_id: int, description: str = Form("")):
    with Session(engine) as s:
        v = s.get(Vehicle, vehicle_id)
        if v:
            v.description = description.strip()
            s.commit()
    return RedirectResponse(f"/vehicle/{vehicle_id}", status_code=303)

@app.post("/vehicle/{vehicle_id}/upload_doc")
def upload_doc(vehicle_id: int, file: UploadFile = File(...)):
    filename = f"{vehicle_id}_{int(datetime.datetime.utcnow().timestamp())}_{file.filename}"
    path = os.path.join("uploads","vehicle_docs",filename)
    with open(path,"wb") as f:
        f.write(file.file.read())
    with Session(engine) as s:
        d = VehicleDoc(vehicle_id=vehicle_id, filename=filename, orig_name=file.filename, uploaded_at=datetime.datetime.utcnow().isoformat())
        s.add(d); s.commit()
    return RedirectResponse(f"/vehicle/{vehicle_id}", status_code=303)

from fastapi import Response
@app.get("/vehicle/{vehicle_id}/doc/{doc_id}/download")
def download_doc(vehicle_id: int, doc_id: int):
    with Session(engine) as s:
        d = s.get(VehicleDoc, doc_id)
        if not d or d.vehicle_id != vehicle_id:
            return RedirectResponse(f"/vehicle/{vehicle_id}", status_code=303)
        path = os.path.join("uploads","vehicle_docs", d.filename)
        return StreamingResponse(open(path,"rb"), media_type="application/octet-stream", 
            headers={"Content-Disposition": f'attachment; filename="{d.orig_name}"'})

@app.post("/item/{item_id}/upload_photo")
def upload_item_photo(item_id: int, photo: UploadFile = File(...)):
    ext = os.path.splitext(photo.filename)[1].lower() or ".bin"
    filename = f"item_{item_id}_{int(datetime.datetime.utcnow().timestamp())}{ext}"
    path = os.path.join("uploads","items", filename)
    with open(path,"wb") as f:
        f.write(photo.file.read())
    with Session(engine) as s:
        it = s.get(Item, item_id)
        if it:
            it.photo_filename = filename
            s.commit()
            vehicle_id = it.place.vehicle_id if it.place else 0
    if vehicle_id:
        return RedirectResponse(f"/vehicle/{vehicle_id}?open_place={it.place_id}&highlight_item={it.id}", status_code=303)
    return RedirectResponse("/", status_code=303)

@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request, msg: str | None = None):
    return templates.TemplateResponse("upload.html", {"request":request, "msg":msg, "logged": is_logged(request)})

@app.post("/upload")
def upload_csv(file: UploadFile = File(...)):
    content = file.file.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    with Session(engine) as s:
        cache_v = {}; cache_p = {}
        for row in reader:
            vname = (row.get("Vehicle") or row.get("Køretøj") or "").strip()
            pname = (row.get("Place") or row.get("Rum") or "").strip()
            iname = (row.get("Item") or row.get("Udstyr") or "").strip()
            qty = int((row.get("Quantity") or row.get("Antal") or "1") or "1")
            note = (row.get("Note") or "").strip() or None
            if not vname or not pname or not iname: 
                continue
            vobj = cache_v.get(vname) or s.execute(select(Vehicle).where(Vehicle.name==vname)).scalar_one_or_none()
            if not vobj:
                vobj = Vehicle(name=vname, sort=0); s.add(vobj); s.flush()
            cache_v[vname] = vobj
            pkey = (vobj.id, pname)
            pobj = cache_p.get(pkey) or s.execute(select(Place).where(Place.vehicle_id==vobj.id, Place.name==pname)).scalar_one_or_none()
            if not pobj:
                pobj = Place(vehicle_id=vobj.id, name=pname, sort=0); s.add(pobj); s.flush()
            cache_p[pkey] = pobj
            s.add(Item(place_id=pobj.id, name=iname, quantity=qty, note=note))
        s.commit()
    return RedirectResponse("/?msg=Import+ok", status_code=303)

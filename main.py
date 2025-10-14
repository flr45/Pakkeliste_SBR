# -*- coding: utf-8 -*-
import os, sqlite3
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, select, func, text, Column, Integer, String, ForeignKey
from sqlalchemy.orm import Session, declarative_base

os.makedirs("uploads", exist_ok=True)
os.makedirs("data", exist_ok=True)

Base = declarative_base()
engine = create_engine("sqlite:///data/app.db", connect_args={"check_same_thread": False})

class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sort = Column(Integer, default=0)
    description = Column(String, default="")

class Place(Base):
    __tablename__ = "places"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sort = Column(Integer, default=0)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    quantity = Column(Integer, default=1)
    note = Column(String, default="")
    sort = Column(Integer, default=0)
    place_id = Column(Integer, ForeignKey("places.id"), nullable=False)
    photo_path = Column(String, default="")

Base.metadata.create_all(engine)

def ensure_schema():
    with sqlite3.connect("data/app.db") as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        def col_missing(table, col):
            cur.execute(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in cur.fetchall()]
            return col not in cols

        if col_missing("vehicles", "description"):
            cur.execute("ALTER TABLE vehicles ADD COLUMN description TEXT DEFAULT ''")
        if col_missing("items", "photo_path"):
            cur.execute("ALTER TABLE items ADD COLUMN photo_path TEXT DEFAULT ''")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_docs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            FOREIGN KEY(vehicle_id) REFERENCES vehicles(id)
        )
        """ )
        con.commit()

ensure_schema()

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="change-me")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

def is_logged(request: Request) -> bool:
    return bool(request.session.get("logged"))

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "logged": is_logged(request)})

@app.get("/vehicles")
def vehicles_page(request: Request):
    with Session(engine) as s:
        rows = s.execute(
            select(Vehicle.id, Vehicle.name, Vehicle.description, func.count(Place.id).label("place_count"))
            .join(Place, Place.vehicle_id == Vehicle.id, isouter=True)
            .group_by(Vehicle.id)
            .order_by(Vehicle.sort, Vehicle.name)
        ).all()
        vehicles = [{"id": r.id, "name": r.name, "description": r.description or "", "place_count": r.place_count or 0} for r in rows]
    return templates.TemplateResponse("index.html", {"request": request, "vehicles": vehicles, "logged": is_logged(request)})

@app.get("/vehicle/{vid}")
def vehicle_detail(request: Request, vid: int):
    with Session(engine) as s:
        v = s.get(Vehicle, vid)
        if not v: raise HTTPException(404, "Køretøj findes ikke")
        places = s.execute(select(Place).where(Place.vehicle_id == vid).order_by(Place.sort, Place.name)).scalars().all()
        place_dicts = []
        for p in places:
            its = s.execute(select(Item).where(Item.place_id == p.id).order_by(Item.sort, Item.name)).scalars().all()
            items_list = [{"id": it.id, "name": it.name, "quantity": it.quantity, "note": it.note, "photo_path": it.photo_path} for it in its]
            place_dicts.append({"id": p.id, "name": p.name, "sort": p.sort, "items_list": items_list, "items_count": len(items_list)})

        docs = s.execute(text("SELECT id, filename, original_name FROM vehicle_docs WHERE vehicle_id=:vid ORDER BY id DESC"), {"vid": vid}).mappings().all()
        data = {"id": v.id, "name": v.name, "description": v.description or "", "places": place_dicts, "docs": list(docs)}

    return templates.TemplateResponse("vehicle.html", {"request": request, "v": data, "logged": is_logged(request)})

@app.post("/place/{pid}/rename")
def rename_place(pid: int, name: str = Form(...)):
    with Session(engine) as s:
        p = s.get(Place, pid)
        if not p: raise HTTPException(404)
        p.name = (name or '').strip()[:200]
        s.commit()
        return JSONResponse({"ok": True, "name": p.name})

@app.post("/vehicle/{vid}/add_place")
def add_place(vid: int, name: str = Form(...)):
    with Session(engine) as s:
        v = s.get(Vehicle, vid)
        if not v: raise HTTPException(404)
        maxsort = s.execute(select(func.coalesce(func.max(Place.sort), 0)).where(Place.vehicle_id == vid)).scalar()
        p = Place(vehicle_id=vid, name=(name or 'Nyt rum').strip(), sort=(maxsort or 0)+10)
        s.add(p); s.commit()
        return RedirectResponse(f"/vehicle/{vid}?msg=Rum+tilføjet", status_code=303)

@app.post("/place/{pid}/add_item")
def add_item(pid: int, name: str = Form(...), quantity: int = Form(1), note: str = Form("")):
    with Session(engine) as s:
        p = s.get(Place, pid)
        if not p: raise HTTPException(404)
        maxsort = s.execute(select(func.coalesce(func.max(Item.sort), 0)).where(Item.place_id == pid)).scalar()
        it = Item(place_id=pid, name=(name or 'Nyt udstyr').strip(), quantity=quantity, note=(note or '').strip(), sort=(maxsort or 0)+10)
        s.add(it); s.commit()
        return JSONResponse({"ok": True, "item_id": it.id})

@app.post("/place/{pid}/move")
def move_place(pid: int, direction: str = Form(...)):
    delta = -11 if direction == "up" else 11
    with Session(engine) as s:
        p = s.get(Place, pid)
        if not p: raise HTTPException(404)
        p.sort = (p.sort or 0) + delta
        s.commit()
    return JSONResponse({"ok": True, "new_sort": p.sort})

@app.post("/item/{iid}/move")
def move_item(iid: int, direction: str = Form(...)):
    delta = -11 if direction == "up" else 11
    with Session(engine) as s:
        it = s.get(Item, iid)
        if not it: raise HTTPException(404)
        it.sort = (it.sort or 0) + delta
        s.commit()
    return JSONResponse({"ok": True, "new_sort": it.sort})

@app.post("/item/{iid}/upload_photo")
def upload_item_photo(iid: int, file: UploadFile = File(...)):
    ext = (Path(file.filename).suffix or "").lower()
    if ext not in [".jpg",".jpeg",".png",".webp",".gif"]:
        raise HTTPException(400, "Kun billede-filtyper er tilladt")
    safe = f"item_{iid}{ext}"
    dest = Path("uploads")/safe
    with dest.open("wb") as f: f.write(file.file.read())
    with Session(engine) as s:
        it = s.get(Item, iid)
        if not it: raise HTTPException(404)
        it.photo_path = f"/uploads/{safe}"
        s.commit()
        pid = it.place_id
        vid = s.execute(select(Place.vehicle_id).where(Place.id==pid)).scalar()
    return RedirectResponse(f"/vehicle/{vid}?msg=Billede+opdateret", status_code=303)

@app.post("/vehicle/{vid}/save_description")
def save_description(vid: int, description: str = Form("")):
    with Session(engine) as s:
        v = s.get(Vehicle, vid)
        if not v: raise HTTPException(404)
        v.description = (description or "")[:5000]
        s.commit()
    return JSONResponse({"ok": True})

@app.post("/vehicle/{vid}/upload_doc")
def upload_vehicle_doc(vid: int, file: UploadFile = File(...)):
    ext = (Path(file.filename).suffix or "").lower()
    safe = f"veh_{vid}_{abs(hash(file.filename))}{ext}"
    dest = Path("uploads")/safe
    with dest.open("wb") as f: f.write(file.file.read())
    with sqlite3.connect("data/app.db") as con:
        con.execute("INSERT INTO vehicle_docs(vehicle_id, filename, original_name) VALUES(?,?,?)", (vid, f"/uploads/{safe}", file.filename))
        con.commit()
    return RedirectResponse(f"/vehicle/{vid}?msg=Dok+upload", status_code=303)

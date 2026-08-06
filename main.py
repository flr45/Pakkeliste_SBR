import csv
import io
import os
import secrets
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, selectinload
from starlette.middleware.sessions import SessionMiddleware

# ----------------------- Config -----------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
SECRET_KEY = os.getenv("APP_SECRET", "change-me")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")

os.makedirs("uploads/items", exist_ok=True)
os.makedirs("uploads/docs", exist_ok=True)

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="pl_sess",
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")


# ----------------------- DB Models -----------------------
class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    places: Mapped[List["Place"]] = relationship(
        back_populates="vehicle",
        cascade="all, delete-orphan",
        order_by="Place.sort, Place.name",
    )
    docs: Mapped[List["VehicleDoc"]] = relationship(
        back_populates="vehicle",
        cascade="all, delete-orphan",
        order_by="VehicleDoc.id",
    )


class VehicleDoc(Base):
    __tablename__ = "vehicle_docs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(400))
    vehicle: Mapped["Vehicle"] = relationship(back_populates="docs")


class Place(Base):
    __tablename__ = "places"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    vehicle: Mapped["Vehicle"] = relationship(back_populates="places")
    items: Mapped[List["Item"]] = relationship(
        back_populates="place",
        cascade="all, delete-orphan",
        order_by="Item.sort, Item.name",
    )


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[Optional[str]] = mapped_column(String(500), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    photo_path: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    place: Mapped["Place"] = relationship(back_populates="items")


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
Base.metadata.create_all(engine)


def db() -> Session:
    return Session(engine)


def is_logged(req: Request) -> bool:
    return bool(req.session.get("user"))


def require_login(req: Request) -> None:
    if not is_logged(req):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


def page_context(request: Request, page: str, **extra):
    return {
        "request": request,
        "logged": is_logged(request),
        "page": page,
        **extra,
    }


def vehicle_payload(vehicle: Vehicle, include_places: bool = False) -> dict:
    places = []
    if include_places:
        places = [
            {
                "id": place.id,
                "name": place.name,
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "note": item.note or "",
                        "photo_path": item.photo_path,
                    }
                    for item in place.items
                ],
            }
            for place in vehicle.places
        ]

    return {
        "id": vehicle.id,
        "name": vehicle.name,
        "description": vehicle.description or "",
        "place_count": len(vehicle.places),
        "item_count": sum(len(place.items) for place in vehicle.places),
        "places": places,
        "docs": [
            {"id": doc.id, "filename": doc.filename, "path": doc.path}
            for doc in vehicle.docs
        ],
    }


# ----------------------- Auth -----------------------
@app.get("/login")
def login_form(request: Request, msg: Optional[str] = None):
    return templates.TemplateResponse(
        "login.html", page_context(request, "login", msg=msg)
    )


@app.post("/login")
def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = username
        return RedirectResponse("/", 303)
    return templates.TemplateResponse(
        "login.html", page_context(request, "login", msg="Forkert login")
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)


# ----------------------- Pages -----------------------
@app.get("/")
def home(request: Request):
    with db() as session:
        rows = session.execute(
            select(Vehicle)
            .options(
                selectinload(Vehicle.places).selectinload(Place.items),
                selectinload(Vehicle.docs),
            )
            .order_by(Vehicle.sort, Vehicle.name)
        ).scalars().all()
        vehicles = [vehicle_payload(vehicle) for vehicle in rows]

    stats = {
        "vehicles": len(vehicles),
        "places": sum(vehicle["place_count"] for vehicle in vehicles),
        "items": sum(vehicle["item_count"] for vehicle in vehicles),
    }
    return templates.TemplateResponse(
        "index.html",
        page_context(request, "home", vehicles=vehicles[:4], stats=stats),
    )


@app.get("/vehicles")
def vehicles_page(request: Request):
    with db() as session:
        rows = session.execute(
            select(Vehicle)
            .options(
                selectinload(Vehicle.places).selectinload(Place.items),
                selectinload(Vehicle.docs),
            )
            .order_by(Vehicle.sort, Vehicle.name)
        ).scalars().all()
        vehicles = [vehicle_payload(vehicle) for vehicle in rows]

    return templates.TemplateResponse(
        "vehicles.html",
        page_context(request, "vehicles", vehicles=vehicles),
    )


@app.post("/vehicles/new")
def create_vehicle(
    request: Request, name: str = Form(...), description: str = Form("")
):
    require_login(request)
    clean_name = name.strip()
    with db() as session:
        exists = session.scalar(
            select(func.count()).select_from(Vehicle).where(Vehicle.name == clean_name)
        )
        if exists:
            return RedirectResponse("/vehicles?msg=Findes%20allerede", 303)
        vehicle = Vehicle(name=clean_name, description=description.strip())
        session.add(vehicle)
        session.commit()
        session.refresh(vehicle)
        return RedirectResponse(f"/vehicle/{vehicle.id}", 303)


@app.get("/vehicle/{vehicle_id}")
def vehicle_detail(request: Request, vehicle_id: int):
    with db() as session:
        vehicle = session.execute(
            select(Vehicle)
            .options(
                selectinload(Vehicle.places).selectinload(Place.items),
                selectinload(Vehicle.docs),
            )
            .where(Vehicle.id == vehicle_id)
        ).scalar_one_or_none()
        if not vehicle:
            return Response("Ikke fundet", status_code=404)
        data = vehicle_payload(vehicle, include_places=True)

    return templates.TemplateResponse(
        "vehicle.html",
        page_context(request, "vehicles", vehicle=data),
    )


@app.get("/vehicle/{vehicle_id}/place/{place_id}")
def place_detail(request: Request, vehicle_id: int, place_id: int):
    with db() as session:
        place = session.execute(
            select(Place)
            .options(selectinload(Place.items), selectinload(Place.vehicle))
            .where(Place.id == place_id, Place.vehicle_id == vehicle_id)
        ).scalar_one_or_none()
        if not place:
            return Response("Ikke fundet", status_code=404)
        data = {
            "id": place.id,
            "name": place.name,
            "vehicle": {"id": place.vehicle.id, "name": place.vehicle.name},
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "note": item.note or "",
                    "photo_path": item.photo_path,
                }
                for item in place.items
            ],
        }

    return templates.TemplateResponse(
        "place.html", page_context(request, "vehicles", place=data)
    )


@app.get("/item/{item_id}")
def item_detail(request: Request, item_id: int):
    with db() as session:
        item = session.execute(
            select(Item)
            .options(selectinload(Item.place).selectinload(Place.vehicle))
            .where(Item.id == item_id)
        ).scalar_one_or_none()
        if not item:
            return Response("Ikke fundet", status_code=404)
        data = {
            "id": item.id,
            "name": item.name,
            "quantity": item.quantity,
            "note": item.note or "",
            "photo_path": item.photo_path,
            "place": {"id": item.place.id, "name": item.place.name},
            "vehicle": {
                "id": item.place.vehicle.id,
                "name": item.place.vehicle.name,
            },
        }

    return templates.TemplateResponse(
        "item.html", page_context(request, "vehicles", item=data)
    )


@app.get("/videos")
def videos_page(request: Request):
    return templates.TemplateResponse(
        "videos.html", page_context(request, "videos")
    )


@app.get("/documents")
def documents_page(request: Request):
    with db() as session:
        docs = session.execute(
            select(VehicleDoc)
            .options(selectinload(VehicleDoc.vehicle))
            .order_by(VehicleDoc.filename)
        ).scalars().all()
        data = [
            {
                "id": doc.id,
                "filename": doc.filename,
                "path": doc.path,
                "vehicle": {"id": doc.vehicle.id, "name": doc.vehicle.name},
            }
            for doc in docs
        ]
    return templates.TemplateResponse(
        "documents.html", page_context(request, "documents", documents=data)
    )


@app.get("/search")
def search_page(request: Request, q: str = ""):
    query = q.strip().lower()
    vehicles = []
    places = []
    items = []

    if query:
        with db() as session:
            vehicle_rows = session.execute(
                select(Vehicle).order_by(Vehicle.name)
            ).scalars().all()
            place_rows = session.execute(
                select(Place)
                .options(selectinload(Place.vehicle))
                .order_by(Place.name)
            ).scalars().all()
            item_rows = session.execute(
                select(Item)
                .options(selectinload(Item.place).selectinload(Place.vehicle))
                .order_by(Item.name)
            ).scalars().all()

            vehicles = [
                {"id": vehicle.id, "name": vehicle.name, "description": vehicle.description or ""}
                for vehicle in vehicle_rows
                if query in vehicle.name.lower()
                or query in (vehicle.description or "").lower()
            ][:20]
            places = [
                {
                    "id": place.id,
                    "name": place.name,
                    "vehicle": {"id": place.vehicle.id, "name": place.vehicle.name},
                }
                for place in place_rows
                if query in place.name.lower()
            ][:20]
            items = [
                {
                    "id": item.id,
                    "name": item.name,
                    "note": item.note or "",
                    "place": {"id": item.place.id, "name": item.place.name},
                    "vehicle": {
                        "id": item.place.vehicle.id,
                        "name": item.place.vehicle.name,
                    },
                }
                for item in item_rows
                if query in item.name.lower() or query in (item.note or "").lower()
            ][:40]

    return templates.TemplateResponse(
        "search.html",
        page_context(
            request,
            "search",
            q=q,
            vehicles=vehicles,
            places=places,
            items=items,
        ),
    )


# ----------------------- Inline edits & adds -----------------------
@app.post("/vehicle/{vehicle_id}/description")
def update_vehicle_description(
    request: Request, vehicle_id: int, description: str = Form("")
):
    require_login(request)
    with db() as session:
        vehicle = session.get(Vehicle, vehicle_id)
        if not vehicle:
            return JSONResponse({"ok": False}, status_code=404)
        vehicle.description = description.strip()
        session.commit()
    return JSONResponse({"ok": True})


@app.post("/vehicle/{vehicle_id}/places/new")
def create_place(request: Request, vehicle_id: int, name: str = Form(...)):
    require_login(request)
    with db() as session:
        vehicle = session.get(Vehicle, vehicle_id)
        if not vehicle:
            return JSONResponse({"ok": False}, status_code=404)
        place = Place(name=name.strip(), vehicle=vehicle)
        session.add(place)
        session.commit()
        session.refresh(place)
        return JSONResponse({"ok": True, "id": place.id, "name": place.name})


@app.post("/place/{place_id}/rename")
def rename_place(request: Request, place_id: int, name: str = Form(...)):
    require_login(request)
    with db() as session:
        place = session.get(Place, place_id)
        if not place:
            return JSONResponse({"ok": False}, status_code=404)
        place.name = name.strip()
        session.commit()
    return JSONResponse({"ok": True})


@app.post("/place/{place_id}/items/new")
def create_item(
    request: Request,
    place_id: int,
    name: str = Form(...),
    quantity: int = Form(1),
    note: str = Form(""),
):
    require_login(request)
    with db() as session:
        place = session.get(Place, place_id)
        if not place:
            return JSONResponse({"ok": False}, status_code=404)
        item = Item(
            name=name.strip(),
            quantity=max(1, int(quantity or 1)),
            note=note.strip(),
            place=place,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return JSONResponse({"ok": True, "id": item.id})


@app.post("/item/{item_id}/photo")
async def upload_item_photo(
    request: Request, item_id: int, file: UploadFile = File(...)
):
    require_login(request)
    ext = os.path.splitext(file.filename or "")[1].lower()
    safe = secrets.token_hex(8) + ext
    path = f"uploads/items/{safe}"
    with open(path, "wb") as output:
        output.write(await file.read())
    with db() as session:
        item = session.get(Item, item_id)
        if not item:
            return JSONResponse({"ok": False}, status_code=404)
        item.photo_path = "/" + path
        session.commit()
    return JSONResponse({"ok": True, "path": "/" + path})


@app.post("/vehicle/{vehicle_id}/docs")
async def upload_vehicle_doc(
    request: Request, vehicle_id: int, file: UploadFile = File(...)
):
    require_login(request)
    original_name = file.filename or "dokument"
    safe = secrets.token_hex(8) + "_" + original_name.replace("/", "_")
    path = f"uploads/docs/{safe}"
    with open(path, "wb") as output:
        output.write(await file.read())
    with db() as session:
        vehicle = session.get(Vehicle, vehicle_id)
        if not vehicle:
            return JSONResponse({"ok": False}, status_code=404)
        doc = VehicleDoc(vehicle=vehicle, filename=original_name, path="/" + path)
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return JSONResponse(
            {"ok": True, "id": doc.id, "filename": doc.filename, "path": doc.path}
        )


# ----------------------- Import / Export -----------------------
def _read_csv_bytes(data: bytes):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError:
            text = data.decode(errors="ignore")
    first = text.splitlines()[0] if text.splitlines() else ""
    delimiter = ";" if ";" in first else ("," if "," in first else ";")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [
        {
            (key or "").strip().lower(): value.strip()
            if isinstance(value, str)
            else value
            for key, value in row.items()
        }
        for row in reader
    ]


@app.get("/upload")
def upload_form(request: Request):
    return templates.TemplateResponse(
        "upload.html", page_context(request, "admin")
    )


@app.post("/upload")
async def do_upload(request: Request, file: UploadFile = File(...)):
    require_login(request)
    rows = _read_csv_bytes(await file.read())
    with db() as session:
        vehicle_cache = {
            vehicle.name.lower(): vehicle
            for vehicle in session.execute(select(Vehicle)).scalars().all()
        }
        for row in rows:
            vehicle_name = (row.get("vehicle") or row.get("køretøj") or "").strip()
            place_name = (
                row.get("place") or row.get("rum") or row.get("kasse") or ""
            ).strip()
            item_name = (
                row.get("item") or row.get("udstyr") or row.get("navn") or ""
            ).strip()
            quantity = row.get("quantity") or row.get("antal") or "1"
            note = row.get("note") or row.get("bemærkning") or ""
            if not (place_name and item_name):
                continue

            vehicle = vehicle_cache.get(vehicle_name.lower()) if vehicle_name else None
            if not vehicle:
                key = vehicle_name.lower() if vehicle_name else "standard"
                vehicle = vehicle_cache.get(key)
                if not vehicle:
                    vehicle = Vehicle(name=vehicle_name or "Standard")
                    session.add(vehicle)
                    session.flush()
                    vehicle_cache[key] = vehicle

            place = next(
                (
                    candidate
                    for candidate in vehicle.places
                    if candidate.name.lower() == place_name.lower()
                ),
                None,
            )
            if not place:
                place = Place(name=place_name, vehicle=vehicle)
                session.add(place)
                session.flush()
            try:
                parsed_quantity = int(str(quantity) or "1")
            except ValueError:
                parsed_quantity = 1
            session.add(
                Item(
                    name=item_name,
                    quantity=max(1, parsed_quantity),
                    note=note,
                    place=place,
                )
            )
        session.commit()
    return RedirectResponse("/vehicles?msg=Import%20ok", 303)


@app.get("/vehicle/{vehicle_id}/export")
def export_vehicle(vehicle_id: int):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Vehicle", "Place", "Item", "Quantity", "Note"])
    with db() as session:
        vehicle = session.execute(
            select(Vehicle)
            .options(selectinload(Vehicle.places).selectinload(Place.items))
            .where(Vehicle.id == vehicle_id)
        ).scalar_one_or_none()
        if not vehicle:
            return Response(status_code=404)
        for place in vehicle.places:
            for item in place.items:
                writer.writerow(
                    [vehicle.name, place.name, item.name, item.quantity, item.note or ""]
                )
        filename = vehicle.name
    data = output.getvalue().encode("utf-8")
    return Response(
        data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}_pakkeliste.csv"'
        },
    )

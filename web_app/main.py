from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import URL

from pet_registry.config import resolve_database_url
from pet_registry.models import (
    PetDetails,
    PetNotFoundError,
    PetValidationError,
    StorageError,
    parse_birth_date,
)
from pet_registry.storage import PetRegistry


WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")


class PetInput(BaseModel):
    name: str = ""
    species: str = ""
    owner: str = ""
    breed: str = ""
    birth_date: str = ""

    def to_details(self) -> PetDetails:
        return PetDetails(
            name=self.name,
            species=self.species,
            owner=self.owner,
            breed=self.breed,
            birth_date=parse_birth_date(self.birth_date),
        )


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if origin is not None and origin != expected:
        raise HTTPException(status_code=403, detail="Откройте форму в реестре питомцев.")


def dashboard(
    request: Request,
    *,
    form: PetInput | None = None,
    pet_id: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    registry: PetRegistry = request.app.state.registry
    days = registry.daily_activity()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "pets": registry.list_pets(),
            "activity": registry.recent_activity(),
            "days": days,
            "peak": max(1, max(count for _, count in days)),
            "form": form if form is not None else PetInput(),
            "pet_id": pet_id,
            "error": error,
        },
        status_code=422 if error else 200,
    )


def save_pet(request: Request, form: PetInput, pet_id: int | None = None) -> Response:
    registry: PetRegistry = request.app.state.registry
    try:
        details = form.to_details()
        if pet_id is None:
            registry.add_pet(details)
        else:
            registry.update_pet(pet_id, details)
    except PetValidationError as error:
        return dashboard(request, form=form, pet_id=pet_id, error=str(error))
    return RedirectResponse(request.url_for("index"), status_code=303)


def create_app(database_url: str | URL | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        url = resolve_database_url() if database_url is None else database_url
        registry = PetRegistry(url)
        app.state.registry = registry
        try:
            yield
        finally:
            registry.close()

    app = FastAPI(title="Реестр питомцев", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, edit: int | None = None) -> HTMLResponse:
        if edit is None:
            return dashboard(request)
        pet = request.app.state.registry.get_pet(edit)
        form = PetInput(
            name=pet.name,
            species=pet.species,
            owner=pet.owner,
            breed=pet.breed,
            birth_date=pet.birth_date.isoformat() if pet.birth_date else "",
        )
        return dashboard(request, form=form, pet_id=pet.id)

    @app.post("/pets", response_class=HTMLResponse, dependencies=[Depends(check_origin)])
    def add_pet(request: Request, form: Annotated[PetInput, Form()]) -> Response:
        return save_pet(request, form)

    @app.post("/pets/{pet_id}/edit", response_class=HTMLResponse, dependencies=[Depends(check_origin)])
    def edit_pet(request: Request, pet_id: int, form: Annotated[PetInput, Form()]) -> Response:
        return save_pet(request, form, pet_id)

    @app.post("/pets/{pet_id}/delete", dependencies=[Depends(check_origin)])
    def delete_pet(request: Request, pet_id: int) -> RedirectResponse:
        request.app.state.registry.delete_pet(pet_id)
        return RedirectResponse(request.url_for("index"), status_code=303)

    @app.exception_handler(PetNotFoundError)
    def pet_not_found(request: Request, error: PetNotFoundError) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name="error.html", context={"error": str(error)}, status_code=404
        )

    @app.exception_handler(StorageError)
    def storage_unavailable(request: Request, error: StorageError) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name="error.html", context={"error": str(error)}, status_code=503
        )

    return app


app = create_app()

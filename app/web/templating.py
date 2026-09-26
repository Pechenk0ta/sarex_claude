from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.models import UserRole
from app.web.session import csrf_token, pop_flashes

WEB_DIR = Path(__file__).parent
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.globals["csrf_token"] = csrf_token
templates.env.globals["pop_flashes"] = pop_flashes
templates.env.filters["weekday"] = lambda d: WEEKDAYS[d.weekday()]
templates.env.filters["ru_date"] = lambda d: d.strftime("%d.%m.%Y")
templates.env.filters["ddmm"] = lambda d: d.strftime("%d.%m")


def _local_dt(moment: datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return moment.astimezone(ZoneInfo(get_settings().app_timezone)).strftime(fmt)


templates.env.filters["local_dt"] = _local_dt


def render(request: Request, name: str, status_code: int = 200, **context: Any) -> Response:
    user = getattr(request.state, "user", None)
    context.setdefault("user", user)
    context.setdefault("is_admin", user is not None and user.role is UserRole.ADMIN)
    context.setdefault("section", request.url.path.strip("/").split("/")[0])
    return templates.TemplateResponse(request, name, context, status_code=status_code)

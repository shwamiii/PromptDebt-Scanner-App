"""One error shape for every failure: {"error": {"code": "...", "message": "..."}}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"] if p != "body")
        message = f"{field}: {first['msg']}" if field else first["msg"]
        return JSONResponse(_body("invalid_input", message), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.webhook import router as webhook_router
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Bot inicializado")
    yield
    logger.info("Bot finalizado")


app = FastAPI(
    title="Bot Atendimento Maquiagem",
    description="WhatsApp + Claude + Google Calendar",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.get("/")
async def root() -> dict:
    return {"status": "online", "service": "bot-maquiagem"}


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}

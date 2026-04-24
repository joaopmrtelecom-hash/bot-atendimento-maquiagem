from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.webhook import router as webhook_router
from app.services.memory import memory
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Executado no startup e shutdown da aplicação."""
    # Startup
    memory.init_db()
    logger.info("Bot inicializado")
    yield
    # Shutdown (nada por enquanto)


app = FastAPI(
    title="Bot Atendimento Maquiagem",
    description="Bot WhatsApp com Claude para Studio Tai Vilela",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


@app.get("/")
async def root() -> dict:
    return {"service": "bot-atendimento-maquiagem", "status": "running"}

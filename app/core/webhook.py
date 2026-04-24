from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.services.claude import claude
from app.services.whatsapp import whatsapp
from app.utils.logger import logger

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> int:
    """
    Verificação do webhook pela Meta (handshake inicial).
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.webhook_verify_token:
        logger.info("Webhook verificado com sucesso pela Meta")
        return int(hub_challenge)

    logger.warning(
        f"Verificação falhou | mode={hub_mode} | "
        f"token_ok={hub_verify_token == settings.webhook_verify_token}"
    )
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_message(request: Request) -> dict:
    """
    Recebe eventos do WhatsApp (mensagens, status, etc.).
    """
    payload = await request.json()
    logger.info(f"Webhook recebido: {payload}")

    try:
        entry = payload.get("entry", [])
        if not entry:
            return {"status": "no_entry"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "no_changes"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        if not messages:
            statuses = value.get("statuses", [])
            if statuses:
                logger.info(f"Status update: {statuses[0].get('status')}")
            return {"status": "no_message"}

        msg = messages[0]
        msg_type = msg.get("type")
        sender = msg.get("from")

        if msg_type != "text":
            logger.info(f"Tipo '{msg_type}' ignorado no bot")
            await whatsapp.send_text(
                to=sender,
                body="Por enquanto só entendo mensagens de texto 🙂",
            )
            return {"status": "non_text_ignored"}

        body = msg["text"]["body"]
        logger.info(f"Mensagem recebida de {sender}: '{body}'")

        # Gera resposta com Claude
        reply = await claude.generate_reply(body)

        await whatsapp.send_text(to=sender, body=reply)

        return {"status": "ok"}

    except Exception as e:
        logger.exception(f"Erro processando webhook: {e}")
        return {"status": "error", "detail": str(e)}

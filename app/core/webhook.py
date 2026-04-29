from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.services.claude import claude
from app.services.memory import Intent, memory
from app.services.prompts.social import SOCIAL_SYSTEM_PROMPT
from app.services.prompts.welcome import WELCOME_SYSTEM_PROMPT
from app.services.router import router as intent_router
from app.services.whatsapp import whatsapp
from app.utils.logger import logger

router = APIRouter()


# Mapeia intent -> (system_prompt, nome_do_agente)
AGENT_PROMPTS: dict[Intent, tuple[str, str]] = {
    "unknown": (WELCOME_SYSTEM_PROMPT, "welcome"),
    "social": (SOCIAL_SYSTEM_PROMPT, "social"),
    # Próximos a implementar:
    # "noiva": (NOIVA_SYSTEM_PROMPT, "noiva"),
    # "debut": (DEBUT_SYSTEM_PROMPT, "debut"),
    # "automaq": (AUTOMAQ_SYSTEM_PROMPT, "automaq"),
    # "vip": (VIP_SYSTEM_PROMPT, "vip"),
}


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> int:
    """Verificação do webhook pela Meta (handshake inicial)."""
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
    """Recebe eventos do WhatsApp (mensagens, status, etc.)."""
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
            logger.info(f"Tipo '{msg_type}' ignorado")
            await whatsapp.send_text(
                to=sender,
                body="Por enquanto só entendo mensagens de texto 🙂",
            )
            return {"status": "non_text_ignored"}

        body = msg["text"]["body"]
        logger.info(f"Mensagem recebida de {sender}: '{body}'")

        # 1) Roteia: identifica ou recupera intent atual
        intent = await intent_router.route(wa_id=sender, user_message=body)

        # 2) Se intent é 'human' ou um serviço ainda não implementado,
        #    o bot fica em silêncio. A secretária real assume.
        if intent == "human" or (
            intent != "unknown" and not intent_router.is_implemented(intent)
        ):
            logger.info(
                f"Bot silencia | wa_id={sender} | intent={intent} "
                f"(humano deve assumir)"
            )
            # Persiste a mensagem da cliente, mas NÃO responde nem persiste resposta do bot.
            # A resposta humana, quando vier, será uma mensagem de fora do bot.
            memory.add(sender, "user", body)
            # Registra a intent num "marcador" — uma assistant message vazia com a intent.
            # Isso garante sticky: próxima mensagem da cliente continua roteando como
            # 'human' / serviço-não-implementado e mantendo o bot calado.
            memory.add(sender, "assistant", "[bot silenciou — humano assumiu]", intent=intent)
            return {"status": "silenced", "intent": intent}

        # 3) Carrega histórico e dispara o agente correspondente
        history = memory.get_history(sender)
        # Filtra mensagens marcadoras vazias do histórico (não mandar pro Claude)
        history = [m for m in history if m["content"] != "[bot silenciou — humano assumiu]"]
        logger.info(
            f"Histórico carregado | wa_id={sender} | "
            f"{len(history)} mensagens | intent={intent}"
        )

        system_prompt, agent_name = AGENT_PROMPTS[intent]
        reply = await claude.generate_reply(
            system_prompt=system_prompt,
            user_message=body,
            history=history,
            agent_name=agent_name,
        )

        # 4) Persiste mensagens (intent fica registrada na resposta do bot)
        memory.add(sender, "user", body)
        memory.add(sender, "assistant", reply, intent=intent)

        # 5) Envia resposta
        await whatsapp.send_text(to=sender, body=reply)

        return {"status": "ok", "intent": intent, "agent": agent_name}

    except Exception as e:
        logger.exception(f"Erro processando webhook: {e}")
        return {"status": "error", "detail": str(e)}

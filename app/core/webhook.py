from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.services.claude import claude
from app.services.memory import Intent, memory
from app.services.prompts.objection_followup import OBJECTION_FOLLOWUP_SYSTEM_PROMPT
from app.services.prompts.social import SOCIAL_SYSTEM_PROMPT
from app.services.prompts.welcome import WELCOME_SYSTEM_PROMPT
from app.services.router import router as intent_router
from app.services.whatsapp import whatsapp
from app.utils.logger import logger

router = APIRouter()


# Frases que indicam o handoff do social para humano
_HANDOFF_MARKERS = (
    "conferindo a agenda",
    "conferindo nossa agenda",
    "verificando a agenda",
    "verificando nossa agenda",
    "já te passo os horários",
    "ja te passo os horarios",
)


def _is_social_handoff(reply: str) -> bool:
    """
    Detecta se a resposta do agente social é a mensagem de encerramento
    (etapa 5: 'estou conferindo a agenda'). Quando essa mensagem é detectada,
    a intent migra de 'social' para 'human' — bot silencia ou responde só objeções.
    """
    lower = reply.lower()
    return any(marker in lower for marker in _HANDOFF_MARKERS)


# Mapeia intent -> (system_prompt, nome_do_agente)
AGENT_PROMPTS: dict[Intent, tuple[str, str]] = {
    "unknown": (WELCOME_SYSTEM_PROMPT, "welcome"),
    "social": (SOCIAL_SYSTEM_PROMPT, "social"),
    "objection_followup": (OBJECTION_FOLLOWUP_SYSTEM_PROMPT, "objection_followup"),
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
    """Recebe eventos do WhatsApp."""
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

        # 1) Roteia
        intent = await intent_router.route(wa_id=sender, user_message=body)

        # 2) Silenciar se intent é human ou serviço não-implementado
        if intent == "human" or (
            intent not in {"unknown", "objection_followup"}
            and not intent_router.is_implemented(intent)
        ):
            logger.info(
                f"Bot silencia | wa_id={sender} | intent={intent}"
            )
            memory.add(sender, "user", body)
            memory.add(
                sender,
                "assistant",
                "[bot silenciou — humano assumiu]",
                intent=intent,
            )
            return {"status": "silenced", "intent": intent}

        # 3) Carrega histórico (filtra marcadores)
        history = memory.get_history(sender)
        history = [
            m for m in history
            if m["content"] != "[bot silenciou — humano assumiu]"
        ]
        logger.info(
            f"Histórico carregado | wa_id={sender} | "
            f"{len(history)} mensagens | intent={intent}"
        )

        # 4) Dispara agente correspondente
        system_prompt, agent_name = AGENT_PROMPTS[intent]
        reply = await claude.generate_reply(
            system_prompt=system_prompt,
            user_message=body,
            history=history,
            agent_name=agent_name,
        )

        # 5) Persiste mensagens.
        # Detecção: se o agente social terminou com "estou conferindo a agenda",
        # marca intent como 'human' na resposta — nas próximas mensagens, o bot
        # silencia ou responde objeções.
        intent_to_save: Intent = intent
        if intent == "social" and _is_social_handoff(reply):
            logger.info(
                f"Handoff detectado | wa_id={sender} | "
                f"intent migrada de 'social' → 'human'"
            )
            intent_to_save = "human"

        memory.add(sender, "user", body)
        memory.add(sender, "assistant", reply, intent=intent_to_save)

        # 6) Envia resposta
        await whatsapp.send_text(to=sender, body=reply)

        return {"status": "ok", "intent": intent, "agent": agent_name}

    except Exception as e:
        logger.exception(f"Erro processando webhook: {e}")
        return {"status": "error", "detail": str(e)}

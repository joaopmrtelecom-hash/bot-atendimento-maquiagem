from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.services.calendar import calendar_service
from app.services.claude import claude
from app.services.memory import Intent, memory
from app.services.prompts.objection_followup import OBJECTION_FOLLOWUP_SYSTEM_PROMPT
from app.services.prompts.social import SOCIAL_TOOLS, get_social_system_prompt
from app.services.prompts.welcome import WELCOME_SYSTEM_PROMPT
from app.services.router import router as intent_router
from app.services.whatsapp import whatsapp
from app.utils.logger import logger

router = APIRouter()


# Marcadores especiais que o agente pode incluir na resposta
HANDOFF_MARKERS = (
    "conferindo a agenda",
    "conferindo nossa agenda",
    "verificando a agenda",
    "verificando nossa agenda",
    "já te passo os horários",
    "ja te passo os horarios",
)
INDISPONIBILIDADE_MARKER = "[AGENDA_INDISPONIVEL]"


def _is_social_handoff(reply: str) -> bool:
    lower = reply.lower()
    return any(marker in lower for marker in HANDOFF_MARKERS)


def _has_indisponibilidade_marker(reply: str) -> bool:
    return INDISPONIBILIDADE_MARKER in reply


def _strip_marker(reply: str) -> str:
    return reply.replace(INDISPONIBILIDADE_MARKER, "").strip()


# Builder de configuração por agente. Permite system prompt dinâmico.
def _agent_config(intent: Intent) -> tuple[str, str, list | None]:
    """Retorna (system_prompt, agent_name, tools) pra cada intent."""
    if intent == "unknown":
        return (WELCOME_SYSTEM_PROMPT, "welcome", None)
    if intent == "social":
        return (get_social_system_prompt(), "social", SOCIAL_TOOLS)
    if intent == "objection_followup":
        return (OBJECTION_FOLLOWUP_SYSTEM_PROMPT, "objection_followup", None)
    raise KeyError(f"Sem agente configurado pra intent: {intent}")


# ============================================================
# Tool executor
# ============================================================
async def _execute_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Despacha tool calls do Claude pra implementação concreta.
    """
    if tool_name == "verificar_disponibilidade":
        data_str = tool_input.get("data")
        hora_str = tool_input.get("hora_pronta")
        duracao = tool_input.get("duracao_minutos", 60)

        if not data_str or not hora_str:
            return {
                "available": False,
                "reason": "input_invalido",
                "details": "Faltou data ou hora_pronta.",
            }

        try:
            tz = ZoneInfo(settings.studio_timezone)
            ready_dt = datetime.fromisoformat(f"{data_str}T{hora_str}").replace(tzinfo=tz)
        except ValueError as e:
            logger.warning(f"Tool verificar_disponibilidade: data/hora inválidas | {e}")
            return {
                "available": False,
                "reason": "input_invalido",
                "details": f"Data ou hora em formato inválido: {data_str} {hora_str}",
            }

        result = calendar_service.find_available_slot(
            ready_dt=ready_dt, duration_minutes=duracao,
        )
        return result

    return {"error": f"tool desconhecida: {tool_name}"}


# ============================================================
# Webhook handlers
# ============================================================
@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> int:
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
            logger.info(f"Bot silencia | wa_id={sender} | intent={intent}")
            memory.add(sender, "user", body)
            memory.add(
                sender, "assistant",
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
        system_prompt, agent_name, tools = _agent_config(intent)
        result = await claude.generate_reply(
            system_prompt=system_prompt,
            user_message=body,
            history=history,
            agent_name=agent_name,
            tools=tools,
            tool_executor=_execute_tool if tools else None,
        )
        reply = result["text"]

        # 5) Detecta marcador de indisponibilidade
        if _has_indisponibilidade_marker(reply):
            cleaned_reply = _strip_marker(reply)
            logger.info(
                f"Indisponibilidade detectada | wa_id={sender} | "
                f"intent migrada para 'human' (silêncio após esta resposta)"
            )

            memory.add(sender, "user", body)
            memory.add(sender, "assistant", cleaned_reply, intent="human")

            await whatsapp.send_text(to=sender, body=cleaned_reply)
            return {"status": "ok", "intent": "human", "agent": agent_name, "reason": "indisponivel"}

        # 6) Detecta handoff normal (Etapa 5 do social)
        intent_to_save: Intent = intent
        if intent == "social" and _is_social_handoff(reply):
            logger.info(
                f"Handoff detectado | wa_id={sender} | "
                f"intent migrada de 'social' → 'human'"
            )
            intent_to_save = "human"

        memory.add(sender, "user", body)
        memory.add(sender, "assistant", reply, intent=intent_to_save)

        # 7) Envia resposta
        await whatsapp.send_text(to=sender, body=reply)

        return {"status": "ok", "intent": intent, "agent": agent_name}

    except Exception as e:
        logger.exception(f"Erro processando webhook: {e}")
        return {"status": "error", "detail": str(e)}

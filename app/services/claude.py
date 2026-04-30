"""
Cliente Claude para geração de respostas.

Aceita system prompt dinâmico para suportar múltiplos agentes
(welcome, social, objection_followup, e futuros: noiva, debut, automaq, vip).
"""
from anthropic import AsyncAnthropic

from app.config import settings
from app.utils.logger import logger


# Comprimento máximo do reply a logar (evita poluir log com mensagens longas)
REPLY_LOG_PREVIEW = 200


class ClaudeService:
    """Cliente Anthropic genérico para gerar respostas com qualquer system prompt."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens

    async def generate_reply(
        self,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        agent_name: str = "agent",
    ) -> str:
        """
        Gera resposta usando o system prompt fornecido.

        Args:
            system_prompt: o system prompt do agente que deve responder.
            user_message: mensagem atual da cliente.
            history: lista de mensagens anteriores no formato
                [{"role": "user" | "assistant", "content": "..."}].
            agent_name: identificador do agente pra log (ex: "welcome", "social").

        Returns:
            Texto da resposta do Claude.
        """
        history = history or []
        messages = [*history, {"role": "user", "content": user_message}]

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages,
            )

            reply = response.content[0].text.strip()

            # Preview da resposta no log (truncado pra não poluir)
            preview = reply.replace("\n", " ↵ ")
            if len(preview) > REPLY_LOG_PREVIEW:
                preview = preview[:REPLY_LOG_PREVIEW] + "..."

            logger.info(
                f"Agente {agent_name!r} respondeu | msgs_context={len(messages)} | "
                f"input_tokens={response.usage.input_tokens} "
                f"output_tokens={response.usage.output_tokens} | reply={preview!r}"
            )

            return reply

        except Exception as e:
            logger.exception(f"Erro ao chamar Claude (agent={agent_name}): {e}")
            return "Desculpe, tive um probleminha técnico aqui. Pode repetir a mensagem?"


claude = ClaudeService()

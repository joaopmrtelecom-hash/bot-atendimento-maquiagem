"""
Cliente Claude para geração de respostas.

Fase 3.5: com memória de conversa (histórico via SQLite).
"""
from anthropic import AsyncAnthropic

from app.config import settings
from app.services.prompts.gisele import SYSTEM_PROMPT_GISELE
from app.utils.logger import logger


class ClaudeService:
    """Cliente Anthropic para gerar respostas com contexto de histórico."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens
        self.system_prompt = SYSTEM_PROMPT_GISELE

    async def generate_reply(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """
        Gera resposta considerando o histórico de conversa.

        Args:
            user_message: mensagem atual da cliente.
            history: lista de mensagens anteriores no formato
                [{"role": "user" | "assistant", "content": "..."}].
                Deve estar em ordem cronológica crescente (mais antiga primeiro)
                e NÃO deve incluir a mensagem atual.

        Returns:
            texto da resposta do Claude.
        """
        history = history or []

        # Monta a lista de mensagens: histórico + mensagem atual
        messages = [*history, {"role": "user", "content": user_message}]

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=messages,
            )

            reply = response.content[0].text.strip()

            logger.info(
                f"Claude respondeu | msgs_context={len(messages)} | "
                f"input_tokens={response.usage.input_tokens} "
                f"output_tokens={response.usage.output_tokens}"
            )

            return reply

        except Exception as e:
            logger.exception(f"Erro ao chamar Claude: {e}")
            return "Desculpe, tive um probleminha técnico aqui. Pode repetir a mensagem?"


claude = ClaudeService()

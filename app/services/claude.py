"""
Cliente Claude para geração de respostas.

Fase 3: persona Gisele (secretária virtual do Studio Tai Vilela).
"""
from anthropic import AsyncAnthropic

from app.config import settings
from app.services.prompts.gisele import SYSTEM_PROMPT_GISELE
from app.utils.logger import logger


class ClaudeService:
    """Cliente Anthropic para gerar respostas."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens
        self.system_prompt = SYSTEM_PROMPT_GISELE

    async def generate_reply(self, user_message: str) -> str:
        """
        Gera resposta para uma mensagem do usuário.
        Stateless por enquanto — cada mensagem é tratada isoladamente.
        Memória de conversa será adicionada na Fase 4.
        """
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[
                    {"role": "user", "content": user_message},
                ],
            )

            reply = response.content[0].text.strip()

            logger.info(
                f"Claude respondeu | input_tokens={response.usage.input_tokens} "
                f"output_tokens={response.usage.output_tokens}"
            )

            return reply

        except Exception as e:
            logger.exception(f"Erro ao chamar Claude: {e}")
            return "Desculpe, tive um probleminha técnico aqui. Pode repetir a mensagem?"


claude = ClaudeService()

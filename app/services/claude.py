"""
Cliente Claude para geração de respostas.

Fase 3 (provisória): prompt genérico, sem persona ainda.
"""
from anthropic import AsyncAnthropic

from app.config import settings
from app.utils.logger import logger


SYSTEM_PROMPT_PROVISORIO = """Você é uma assistente virtual de atendimento via WhatsApp.

Responda com naturalidade, em português brasileiro, com tom acolhedor e profissional.
Mantenha as respostas curtas (máximo 3 frases) e evite linguagem robótica.

Por enquanto, ainda não tenho instruções específicas sobre produtos ou serviços.
Se a pessoa perguntar algo específico, diga que vai verificar e retornará em breve."""


class ClaudeService:
    """Cliente Anthropic para gerar respostas."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens

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
                system=SYSTEM_PROMPT_PROVISORIO,
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

"""
Roteador de intent — classifica a mensagem da cliente e direciona pro agente certo.

Fluxo:
1. Lê intent atual do banco (default 'unknown')
2. Se intent já é de serviço (social, noiva, etc.), mantém — não re-classifica
   (decisão arquitetural: roteador roda só na 1ª mensagem)
3. Se intent é 'unknown', chama o classifier silencioso pra ver se a mensagem
   atual já permite identificar o serviço
4. Se o classifier retornar 'human', registra e bot fica em silêncio
5. Retorna a intent final pra usar na resposta
"""
import json

from anthropic import AsyncAnthropic

from app.config import settings
from app.services.memory import Intent, memory
from app.services.prompts.classifier import CLASSIFIER_SYSTEM_PROMPT
from app.utils.logger import logger


# Intents que o bot já sabe atender (Fase 4.1: só social)
IMPLEMENTED_INTENTS: set[Intent] = {"social"}


class IntentRouter:
    """Decide qual agente vai responder à mensagem atual."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def classify(
        self,
        wa_id: str,
        user_message: str,
        recent_context: str | None = None,
    ) -> Intent:
        """
        Classifica a mensagem da cliente. Retorna uma intent.

        Args:
            wa_id: ID do WhatsApp da cliente
            user_message: a mensagem atual
            recent_context: contexto resumido do histórico recente (opcional)

        Returns:
            Intent identificada.
        """
        # Monta a mensagem pro classifier
        prompt = f"Mensagem: {user_message!r}"
        if recent_context:
            prompt += f"\nContexto atual: {recent_context}"
        else:
            prompt += "\nContexto atual: nenhum"
        prompt += '\n\nResponda APENAS com o JSON. Exemplo: {"intent": "social"}'

        try:
            response = await self.client.messages.create(
                model=settings.classifier_model,
                max_tokens=64,
                system=CLASSIFIER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            logger.info(
                f"Classifier respondeu | wa_id={wa_id} | "
                f"input_tokens={response.usage.input_tokens} "
                f"output_tokens={response.usage.output_tokens} | raw={raw!r}"
            )

            # Parsear o JSON com tolerância a markdown ou texto extra
            intent = self._extract_intent(raw)
            return intent

        except Exception as e:
            logger.exception(f"Erro no classifier: {e}")
            return "unknown"  # falha = mantém genérico

    def _extract_intent(self, raw: str) -> Intent:
        """
        Extrai a intent de uma resposta do classifier.
        Tolera respostas com markdown ou whitespace extra.
        """
        # Remove possíveis cercas de markdown
        cleaned = raw.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(cleaned)
            intent = data.get("intent", "unknown")
            valid_intents = {"unknown", "social", "noiva", "debut", "automaq", "vip", "human"}
            if intent not in valid_intents:
                logger.warning(f"Intent inválida do classifier: {intent!r}")
                return "unknown"
            return intent
        except json.JSONDecodeError:
            logger.warning(f"Falha ao parsear JSON do classifier: {cleaned!r}")
            return "unknown"

    async def route(self, wa_id: str, user_message: str) -> Intent:
        """
        Decide a intent ativa pra essa conversa.

        Lógica sticky: se cliente já tem intent definida (que não seja unknown),
        respeita. Só classifica se ainda for unknown.
        """
        current = memory.get_current_intent(wa_id)

        if current != "unknown":
            logger.info(f"Intent sticky | wa_id={wa_id} | intent={current}")
            return current

        # Cliente nova ou ainda sem intent definida — classifica
        new_intent = await self.classify(wa_id=wa_id, user_message=user_message)
        logger.info(f"Intent classificada | wa_id={wa_id} | intent={new_intent}")
        return new_intent

    @staticmethod
    def is_implemented(intent: Intent) -> bool:
        """Retorna True se temos agente especializado pra essa intent."""
        return intent in IMPLEMENTED_INTENTS


router = IntentRouter()

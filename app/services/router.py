"""
Roteador de intent — classifica e direciona mensagens da cliente.

Regras de stickiness:
- Se intent atual é um serviço (social/noiva/debut/automaq/vip): sticky.
  Não re-classifica em mensagens subsequentes.
- Se intent atual é `human`: NÃO sticky. Re-classifica toda mensagem para
  detectar se a cliente fez uma objeção (vira `objection_followup`) ou
  continua sendo coisa pra humano.
- Se intent atual é `unknown`: classifica.

O classifier recebe como contexto as últimas 4 mensagens da conversa,
para resolver ambiguidades em respostas curtas (ex: "social" sozinho,
"festa", "noiva" — sem contexto, parecem genéricos; com contexto, ficam claros).
"""
import json

from anthropic import AsyncAnthropic

from app.config import settings
from app.services.memory import Intent, memory
from app.services.prompts.classifier import CLASSIFIER_SYSTEM_PROMPT
from app.utils.logger import logger


# Intents que o bot já sabe atender (Fase 4.1: social + objection_followup)
IMPLEMENTED_INTENTS: set[Intent] = {"social", "objection_followup"}

# Quantas mensagens recentes mandar como contexto pro classifier
CLASSIFIER_CONTEXT_SIZE = 4


class IntentRouter:
    """Decide qual agente vai responder à mensagem atual."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def classify(
        self,
        wa_id: str,
        user_message: str,
        current_intent: Intent,
    ) -> Intent:
        """
        Classifica a mensagem atual considerando a intent atual e o contexto
        recente da conversa.
        """
        # Carrega últimas N mensagens pra dar contexto
        recent = memory.get_history(wa_id, limit=CLASSIFIER_CONTEXT_SIZE)
        # Filtra marcadores internos
        recent = [
            m for m in recent
            if m["content"] != "[bot silenciou — humano assumiu]"
        ]

        # Monta contexto legível
        if recent:
            context_lines = []
            for m in recent:
                who = "Cliente" if m["role"] == "user" else "Atendente"
                # Trunca conteúdo muito longo pra economizar tokens no classifier
                content = m["content"]
                if len(content) > 300:
                    content = content[:300] + "..."
                context_lines.append(f"{who}: {content}")
            context_str = "\n".join(context_lines)
        else:
            context_str = "(nenhuma mensagem anterior)"

        prompt = (
            f"Histórico recente da conversa:\n{context_str}\n\n"
            f"Mensagem atual da cliente: {user_message!r}\n"
            f"Intent atual: {current_intent}\n\n"
            'Responda APENAS com o JSON. Exemplo: {"intent": "social"}'
        )

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
            return self._extract_intent(raw)

        except Exception as e:
            logger.exception(f"Erro no classifier: {e}")
            return current_intent if current_intent != "unknown" else "unknown"

    def _extract_intent(self, raw: str) -> Intent:
        """Extrai a intent de uma resposta do classifier (tolera markdown extra)."""
        cleaned = raw.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(cleaned)
            intent = data.get("intent", "unknown")
            valid_intents = {
                "unknown", "social", "noiva", "debut",
                "automaq", "vip", "human", "objection_followup",
            }
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

        Lógica:
        - Se intent atual é unknown ou human: classifica.
        - Se intent é um serviço (social, noiva, etc.): sticky.
        - objection_followup nunca é "sticky" — é transitória.
        """
        current = memory.get_current_intent(wa_id)

        # Sticky: serviço implementado mantém
        if current not in {"unknown", "human", "objection_followup"}:
            logger.info(f"Intent sticky | wa_id={wa_id} | intent={current}")
            return current

        # Re-classifica
        new_intent = await self.classify(
            wa_id=wa_id,
            user_message=user_message,
            current_intent=current,
        )
        logger.info(
            f"Intent classificada | wa_id={wa_id} | "
            f"anterior={current} | nova={new_intent}"
        )
        return new_intent

    @staticmethod
    def is_implemented(intent: Intent) -> bool:
        """Retorna True se temos agente especializado pra essa intent."""
        return intent in IMPLEMENTED_INTENTS


router = IntentRouter()

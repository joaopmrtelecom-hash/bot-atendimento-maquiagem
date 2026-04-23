import httpx

from app.config import settings
from app.utils.logger import logger


class WhatsAppService:
    """Cliente HTTP pra Meta Cloud API."""

    def __init__(self) -> None:
        self.base_url = (
            f"{settings.graph_api_base}/{settings.graph_api_version}/"
            f"{settings.phone_number_id}/messages"
        )
        self.headers = {
            "Authorization": f"Bearer {settings.whatsapp_token}",
            "Content-Type": "application/json",
        }

    async def send_text(self, to: str, body: str) -> dict:
        """Envia uma mensagem de texto simples."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.base_url, headers=self.headers, json=payload
            )

        if response.status_code != 200:
            logger.error(
                f"Falha no envio pra {to}: {response.status_code} | {response.text}"
            )
            response.raise_for_status()

        data = response.json()
        msg_id = data.get("messages", [{}])[0].get("id")
        logger.info(f"Mensagem enviada pra {to} | id={msg_id}")
        return data


whatsapp = WhatsAppService()

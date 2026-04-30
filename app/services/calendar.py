"""
Cliente Google Calendar (read-only).

Consulta a agenda da Tai pra verificar disponibilidade. Suporta:
- Bloqueio por sobreposição: qualquer evento que cruza o intervalo solicitado
- Bloqueio por dia: evento all-day bloqueia o dia inteiro
- Janela de horário comercial (STUDIO_OPEN_HOUR a STUDIO_CLOSE_HOUR)

Usa Service Account autenticada via JSON em settings.google_credentials_path.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings
from app.utils.logger import logger


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class CalendarService:
    """Cliente Google Calendar somente leitura."""

    def __init__(self) -> None:
        self.calendar_id = settings.google_calendar_id
        self.timezone = ZoneInfo(settings.studio_timezone)
        self.open_hour = settings.studio_open_hour
        self.close_hour = settings.studio_close_hour
        self._service = None  # build lazy

    def _get_service(self):
        """Constrói o cliente da API na primeira chamada e reutiliza."""
        if self._service is None:
            creds = Credentials.from_service_account_file(
                settings.google_credentials_path,
                scopes=SCOPES,
            )
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def healthcheck(self) -> bool:
        """
        Verifica se a integração está funcional.
        Retorna True se conseguir listar metadata do calendário.
        Use no startup pra falhar rápido em caso de credencial errada.
        """
        try:
            service = self._get_service()
            cal = service.calendars().get(calendarId=self.calendar_id).execute()
            logger.info(
                f"Google Calendar OK | summary={cal.get('summary')!r} | "
                f"timezone={cal.get('timeZone')}"
            )
            return True
        except HttpError as e:
            logger.error(f"Google Calendar falhou no healthcheck: HTTP {e.status_code} {e.reason}")
            return False
        except FileNotFoundError as e:
            logger.error(f"Credencial JSON não encontrada: {e}")
            return False
        except Exception as e:
            logger.exception(f"Google Calendar healthcheck error: {e}")
            return False

    def is_available(
        self,
        start_dt: datetime,
        duration_minutes: int = 60,
    ) -> dict:
        """
        Verifica disponibilidade pra atender em [start_dt, start_dt + duration].

        Retorna um dict com:
            {
                "available": bool,
                "reason": "ok" | "fora_horario_comercial" | "dia_bloqueado" | "horario_ocupado" | "erro",
                "details": str  # explicação humana opcional
            }

        Considera ocupado se:
        - Houver evento all-day no dia (bloqueio do dia inteiro)
        - Houver evento sobrepondo o intervalo
        - O horário estiver fora da janela comercial
        """
        # Garante timezone-awareness
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=self.timezone)
        else:
            start_dt = start_dt.astimezone(self.timezone)

        end_dt = start_dt + timedelta(minutes=duration_minutes)

        # 1. Verifica horário comercial (start E end devem estar dentro)
        if (
            start_dt.hour < self.open_hour
            or end_dt.hour > self.close_hour
            or (end_dt.hour == self.close_hour and end_dt.minute > 0)
        ):
            return {
                "available": False,
                "reason": "fora_horario_comercial",
                "details": (
                    f"Atendimento das {self.open_hour}h às {self.close_hour}h. "
                    f"Solicitado: {start_dt.strftime('%H:%M')} até {end_dt.strftime('%H:%M')}."
                ),
            }

        # 2. Busca eventos do dia
        try:
            day_start = datetime.combine(start_dt.date(), time.min, tzinfo=self.timezone)
            day_end = datetime.combine(start_dt.date(), time.max, tzinfo=self.timezone)

            service = self._get_service()
            result = service.events().list(
                calendarId=self.calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            ).execute()

            events = result.get("items", [])
            logger.info(
                f"Calendar | data={start_dt.date()} | "
                f"eventos_encontrados={len(events)}"
            )

            # 3. Verifica all-day events (bloqueia o dia inteiro)
            for ev in events:
                start = ev.get("start", {})
                if "date" in start and "dateTime" not in start:
                    # all-day: campo 'date' (sem 'dateTime')
                    return {
                        "available": False,
                        "reason": "dia_bloqueado",
                        "details": (
                            f"Há um evento de dia inteiro na agenda em {start_dt.date()}: "
                            f"{ev.get('summary', '(sem título)')!r}"
                        ),
                    }

            # 4. Verifica sobreposição com eventos de horário específico
            for ev in events:
                start = ev.get("start", {})
                end = ev.get("end", {})
                if "dateTime" not in start:
                    continue  # pula all-day (já tratado)

                ev_start = datetime.fromisoformat(start["dateTime"]).astimezone(self.timezone)
                ev_end = datetime.fromisoformat(end["dateTime"]).astimezone(self.timezone)

                # Sobreposição: start < ev_end E end > ev_start
                if start_dt < ev_end and end_dt > ev_start:
                    return {
                        "available": False,
                        "reason": "horario_ocupado",
                        "details": (
                            f"Conflito com evento existente: "
                            f"{ev.get('summary', '(sem título)')!r} "
                            f"das {ev_start.strftime('%H:%M')} às {ev_end.strftime('%H:%M')}."
                        ),
                    }

            # 5. Tudo livre
            return {
                "available": True,
                "reason": "ok",
                "details": (
                    f"Horário disponível: {start_dt.strftime('%d/%m/%Y %H:%M')} "
                    f"às {end_dt.strftime('%H:%M')}."
                ),
            }

        except HttpError as e:
            logger.error(f"Google Calendar API error: {e.status_code} {e.reason}")
            return {
                "available": False,
                "reason": "erro",
                "details": "Erro ao consultar agenda. Sem confirmação de disponibilidade.",
            }
        except Exception as e:
            logger.exception(f"Erro no calendar.is_available: {e}")
            return {
                "available": False,
                "reason": "erro",
                "details": "Erro ao consultar agenda. Sem confirmação de disponibilidade.",
            }


calendar_service = CalendarService()

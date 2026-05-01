"""
Cliente Google Calendar (read-only).

Consulta a agenda da Tai pra verificar disponibilidade.

A regra de busca é "janela de 5h antes do horário de prontidão":
- Cliente diz "preciso estar pronta às X"
- Bot busca qualquer slot de duração D minutos dentro do intervalo
  [max(open_hour, X - lookback_hours), X]
- Se houver ao menos um slot livre nessa janela, está disponível

Bloqueios:
- Eventos de horário específico bloqueiam por sobreposição
- Eventos all-day bloqueiam o dia inteiro
- Slots fora do horário comercial são descartados
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

# Janela de busca antes do horário de prontidão (em horas)
DEFAULT_LOOKBACK_HOURS = 5

# Granularidade dos slots considerados (em minutos). 30min é comum.
SLOT_STEP_MINUTES = 30


class CalendarService:
    """Cliente Google Calendar somente leitura."""

    def __init__(self) -> None:
        self.calendar_id = settings.google_calendar_id
        self.timezone = ZoneInfo(settings.studio_timezone)
        self.open_hour = settings.studio_open_hour
        self.close_hour = settings.studio_close_hour
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = Credentials.from_service_account_file(
                settings.google_credentials_path,
                scopes=SCOPES,
            )
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def healthcheck(self) -> bool:
        """Verifica se a integração está funcional."""
        try:
            service = self._get_service()
            cal = service.calendars().get(calendarId=self.calendar_id).execute()
            logger.info(
                f"Google Calendar OK | summary={cal.get('summary')!r} | "
                f"timezone={cal.get('timeZone')}"
            )
            return True
        except HttpError as e:
            logger.error(f"Google Calendar healthcheck: HTTP {e.status_code} {e.reason}")
            return False
        except FileNotFoundError as e:
            logger.error(f"Credencial JSON não encontrada: {e}")
            return False
        except Exception as e:
            logger.exception(f"Google Calendar healthcheck error: {e}")
            return False

    def _fetch_day_events(self, target_date: date) -> tuple[bool, list[tuple[datetime, datetime]]]:
        """
        Busca eventos do dia.

        Returns:
            (all_day_blocked, busy_intervals)
            - all_day_blocked: True se houver evento all-day no dia
            - busy_intervals: lista de (start, end) timezone-aware, em SP
        """
        day_start = datetime.combine(target_date, time.min, tzinfo=self.timezone)
        day_end = datetime.combine(target_date, time.max, tzinfo=self.timezone)

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
            f"Calendar | data={target_date} | eventos_encontrados={len(events)}"
        )

        all_day_blocked = False
        busy: list[tuple[datetime, datetime]] = []

        for ev in events:
            start = ev.get("start", {})
            end = ev.get("end", {})

            if "date" in start and "dateTime" not in start:
                # All-day event: bloqueia o dia inteiro
                all_day_blocked = True
                logger.info(
                    f"Calendar | all-day event detectado: {ev.get('summary', '(sem título)')!r}"
                )
                continue

            if "dateTime" not in start or "dateTime" not in end:
                continue

            ev_start = datetime.fromisoformat(start["dateTime"]).astimezone(self.timezone)
            ev_end = datetime.fromisoformat(end["dateTime"]).astimezone(self.timezone)
            busy.append((ev_start, ev_end))

        return all_day_blocked, busy

    def _slot_overlaps_busy(
        self,
        slot_start: datetime,
        slot_end: datetime,
        busy_intervals: list[tuple[datetime, datetime]],
    ) -> bool:
        """Retorna True se o slot sobrepõe algum intervalo ocupado."""
        for ev_start, ev_end in busy_intervals:
            if slot_start < ev_end and slot_end > ev_start:
                return True
        return False

    def find_available_slot(
        self,
        ready_dt: datetime,
        duration_minutes: int = 60,
        lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    ) -> dict:
        """
        Verifica se há ao menos um slot livre na janela de busca.

        Args:
            ready_dt: horário em que a cliente precisa estar pronta (timezone-aware ou naive em SP)
            duration_minutes: duração do atendimento (default 60min)
            lookback_hours: quantas horas antes do `ready_dt` aceitar como início válido

        Returns:
            {
                "available": bool,
                "reason": "ok" | "fora_horario_comercial" | "dia_bloqueado"
                          | "horario_ocupado" | "erro",
                "details": str
            }

        Não retorna a lista de slots livres (decisão de produto: humano oferece depois).
        """
        # Garante timezone-aware
        if ready_dt.tzinfo is None:
            ready_dt = ready_dt.replace(tzinfo=self.timezone)
        else:
            ready_dt = ready_dt.astimezone(self.timezone)

        # Define janela [window_start, window_end]
        # window_end = ready_dt (último momento aceito como FIM do atendimento)
        # window_start = max(open_hour do dia, ready_dt - lookback_hours)
        target_date = ready_dt.date()
        day_open = datetime.combine(
            target_date, time(self.open_hour, 0), tzinfo=self.timezone
        )
        day_close = datetime.combine(
            target_date, time(self.close_hour, 0), tzinfo=self.timezone
        )
        window_end = ready_dt
        window_start = max(day_open, ready_dt - timedelta(hours=lookback_hours))

        # Sanity: ready_dt precisa estar dentro do horário comercial
        if ready_dt < day_open or ready_dt > day_close:
            return {
                "available": False,
                "reason": "fora_horario_comercial",
                "details": (
                    f"Atendimento das {self.open_hour}h às {self.close_hour}h. "
                    f"Solicitado estar pronta às {ready_dt.strftime('%H:%M')}."
                ),
            }

        # Sanity: precisa caber pelo menos UM slot na janela
        if window_end - window_start < timedelta(minutes=duration_minutes):
            return {
                "available": False,
                "reason": "fora_horario_comercial",
                "details": (
                    f"Janela muito curta para encaixar um atendimento de "
                    f"{duration_minutes}min antes das {ready_dt.strftime('%H:%M')}."
                ),
            }

        # Busca eventos do dia
        try:
            all_day_blocked, busy = self._fetch_day_events(target_date)
        except HttpError as e:
            logger.error(f"Google Calendar API: {e.status_code} {e.reason}")
            return {
                "available": False,
                "reason": "erro",
                "details": "Erro ao consultar agenda.",
            }
        except Exception as e:
            logger.exception(f"Calendar.find_available_slot: {e}")
            return {
                "available": False,
                "reason": "erro",
                "details": "Erro ao consultar agenda.",
            }

        if all_day_blocked:
            return {
                "available": False,
                "reason": "dia_bloqueado",
                "details": (
                    f"Há um evento de dia inteiro na agenda em {target_date}, "
                    f"bloqueando todo o dia."
                ),
            }

        # Itera slots possíveis: começa em window_start e avança de SLOT_STEP em SLOT_STEP,
        # cada slot dura `duration_minutes`. Slot é válido se:
        #  - termina <= window_end (ou seja, slot_start + duration <= ready_dt)
        #  - NÃO sobrepõe nenhum evento ocupado
        slot_start = window_start
        slot_step = timedelta(minutes=SLOT_STEP_MINUTES)
        slot_duration = timedelta(minutes=duration_minutes)

        while slot_start + slot_duration <= window_end:
            slot_end = slot_start + slot_duration
            if not self._slot_overlaps_busy(slot_start, slot_end, busy):
                # Achou um slot livre!
                return {
                    "available": True,
                    "reason": "ok",
                    "details": (
                        f"Há disponibilidade na janela "
                        f"{window_start.strftime('%H:%M')}–{window_end.strftime('%H:%M')} "
                        f"do dia {target_date.strftime('%d/%m/%Y')}."
                    ),
                }
            slot_start += slot_step

        # Iterou tudo e não achou
        return {
            "available": False,
            "reason": "horario_ocupado",
            "details": (
                f"Janela {window_start.strftime('%H:%M')}–{window_end.strftime('%H:%M')} "
                f"do dia {target_date.strftime('%d/%m/%Y')} está totalmente ocupada."
            ),
        }


calendar_service = CalendarService()

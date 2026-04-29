"""
Gerenciador de histórico de conversas em SQLite.

Armazena mensagens e intent atual de cada cliente indexado pelo wa_id.

Esquema:
- messages(id, wa_id, role, content, intent, timestamp)
- intent é registrado em cada mensagem do bot pra rastrear histórico de roteamento
- a intent ATUAL de uma conversa é a intent da última mensagem do bot
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from app.config import settings
from app.utils.logger import logger


Role = Literal["user", "assistant"]
Intent = Literal["unknown", "social", "noiva", "debut", "automaq", "vip", "human"]


class ConversationMemory:
    """
    Gerencia o histórico de conversas e intent persistida por cliente.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or settings.memory_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        """Context manager que abre conexão, faz commit e fecha."""
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Cria tabela e índices se ainda não existirem; aplica migrações."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wa_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    intent TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_wa_id_ts
                ON messages(wa_id, timestamp)
            """)

            # Migração: adiciona coluna intent se não existir (DB criado na Fase 3.5)
            cols = conn.execute("PRAGMA table_info(messages)").fetchall()
            col_names = {c["name"] for c in cols}
            if "intent" not in col_names:
                logger.info("Migrando schema: adicionando coluna 'intent'")
                conn.execute("ALTER TABLE messages ADD COLUMN intent TEXT")

        logger.info(f"Banco de memória inicializado em {self.db_path}")

    def add(
        self,
        wa_id: str,
        role: Role,
        content: str,
        intent: Intent | None = None,
    ) -> None:
        """
        Adiciona uma mensagem ao histórico. Se for mensagem do assistant,
        registra a intent que estava ativa no momento.
        """
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (wa_id, role, content, intent) VALUES (?, ?, ?, ?)",
                (wa_id, role, content, intent),
            )

    def get_history(
        self, wa_id: str, limit: int | None = None
    ) -> list[dict[str, str]]:
        """
        Retorna as últimas N mensagens do cliente em ordem cronológica crescente,
        no formato esperado pela Anthropic API.
        """
        limit = limit or settings.memory_max_messages
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM (
                    SELECT role, content, timestamp
                    FROM messages
                    WHERE wa_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ) ORDER BY timestamp ASC
                """,
                (wa_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def get_current_intent(self, wa_id: str) -> Intent:
        """
        Retorna a intent da última mensagem do bot pra esse cliente.
        Se não houver, retorna 'unknown'.
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT intent FROM messages
                WHERE wa_id = ? AND role = 'assistant' AND intent IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (wa_id,),
            ).fetchone()
        return row["intent"] if row else "unknown"

    def count(self, wa_id: str) -> int:
        """Total de mensagens armazenadas pra um cliente."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE wa_id = ?", (wa_id,)
            ).fetchone()
        return row["c"] if row else 0

    def clear(self, wa_id: str) -> int:
        """Apaga todo o histórico de um cliente. Retorna quantas foram apagadas."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM messages WHERE wa_id = ?", (wa_id,))
            return cur.rowcount


memory = ConversationMemory()

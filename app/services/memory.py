"""
Gerenciador de histórico de conversas em SQLite.

Armazena mensagens de cada cliente indexadas pelo wa_id (WhatsApp ID).
Permite carregar as últimas N mensagens para dar contexto ao Claude.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from app.config import settings
from app.utils.logger import logger


Role = Literal["user", "assistant"]


class ConversationMemory:
    """
    Gerencia o histórico de conversas por cliente.

    Schema:
        messages(id, wa_id, role, content, timestamp)

    Uso:
        memory = ConversationMemory()
        memory.init_db()
        memory.add("5511989299663", "user", "oi")
        memory.add("5511989299663", "assistant", "Olá! ...")
        history = memory.get_history("5511989299663", limit=20)
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or settings.memory_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        """Context manager que abre conexão, faz commit e fecha."""
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")  # permite leitura durante escrita
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Cria tabela e índices se ainda não existirem."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wa_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_wa_id_ts
                ON messages(wa_id, timestamp)
            """)
        logger.info(f"Banco de memória inicializado em {self.db_path}")

    def add(self, wa_id: str, role: Role, content: str) -> None:
        """Adiciona uma mensagem ao histórico."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (wa_id, role, content) VALUES (?, ?, ?)",
                (wa_id, role, content),
            )

    def get_history(
        self, wa_id: str, limit: int | None = None
    ) -> list[dict[str, str]]:
        """
        Retorna as últimas N mensagens do cliente, ordem cronológica crescente
        (mais antiga primeiro), no formato esperado pela API da Anthropic:

            [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "..."}]
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

    def count(self, wa_id: str) -> int:
        """Retorna o total de mensagens armazenadas pra um cliente."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE wa_id = ?", (wa_id,)
            ).fetchone()
        return row["c"] if row else 0

    def clear(self, wa_id: str) -> int:
        """
        Apaga todo o histórico de um cliente. Retorna o número de mensagens
        apagadas. Útil pra reset em casos excepcionais.
        """
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM messages WHERE wa_id = ?", (wa_id,))
            return cur.rowcount


memory = ConversationMemory()

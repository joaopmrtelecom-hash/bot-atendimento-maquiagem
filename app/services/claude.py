"""
Cliente Claude para geração de respostas com suporte a tool use.

A partir da Fase 4.2, agentes podem ter ferramentas (tools) que o modelo
chama autonomamente — ex: agente social usa `verificar_disponibilidade`
para consultar o Google Calendar.

O loop de tool use é orquestrado em código: enquanto o modelo retornar
tool_use, executamos a ferramenta, devolvemos o resultado e re-chamamos
até obter uma resposta de texto final.
"""
from typing import Any, Awaitable, Callable

from anthropic import AsyncAnthropic

from app.config import settings
from app.utils.logger import logger


REPLY_LOG_PREVIEW = 200
MAX_TOOL_USE_ITERATIONS = 5  # safety: evita loop infinito


class ClaudeService:
    """Cliente Anthropic genérico com suporte a system prompt dinâmico e tool use."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens

    async def generate_reply(
        self,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        agent_name: str = "agent",
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Gera resposta usando o system prompt fornecido. Suporta tool use.

        Args:
            system_prompt: o system prompt do agente.
            user_message: mensagem atual da cliente.
            history: lista de mensagens anteriores (formato Anthropic).
            agent_name: identificador pra log.
            tools: lista de tool definitions (opcional).
            tool_executor: função async que executa tools quando o modelo chama.
                Recebe (tool_name, tool_input) e retorna o result.

        Returns:
            dict com:
                "text": resposta final em texto
                "tool_calls": lista de ferramentas chamadas no caminho (pra log/debug)
        """
        history = history or []
        messages: list[dict[str, Any]] = [
            *history,
            {"role": "user", "content": user_message},
        ]

        tool_calls_log: list[dict[str, Any]] = []
        iterations = 0

        try:
            while iterations < MAX_TOOL_USE_ITERATIONS:
                iterations += 1

                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": system_prompt,
                    "messages": messages,
                }
                if tools:
                    kwargs["tools"] = tools

                response = await self.client.messages.create(**kwargs)

                logger.info(
                    f"Agente {agent_name!r} (iter {iterations}) | "
                    f"stop_reason={response.stop_reason} | "
                    f"input_tokens={response.usage.input_tokens} "
                    f"output_tokens={response.usage.output_tokens}"
                )

                # Se stop_reason for tool_use, processa as tools
                if response.stop_reason == "tool_use" and tool_executor:
                    # Adiciona a resposta do assistant (com tool_use blocks) ao histórico
                    messages.append({
                        "role": "assistant",
                        "content": response.content,
                    })

                    # Executa cada tool_use encontrado
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_input = block.input
                            tool_use_id = block.id

                            logger.info(
                                f"Tool use | agent={agent_name} | "
                                f"name={tool_name} | input={tool_input!r}"
                            )

                            try:
                                result = await tool_executor(tool_name, tool_input)
                                tool_calls_log.append({
                                    "name": tool_name,
                                    "input": tool_input,
                                    "result": result,
                                })
                            except Exception as e:
                                logger.exception(f"Erro executando tool {tool_name}: {e}")
                                result = {"error": str(e)}
                                tool_calls_log.append({
                                    "name": tool_name,
                                    "input": tool_input,
                                    "error": str(e),
                                })

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": str(result),
                            })

                    # Adiciona os tool_results pra o modelo continuar
                    messages.append({
                        "role": "user",
                        "content": tool_results,
                    })
                    continue

                # Não é tool_use ou não temos executor → resposta final
                # Extrai texto dos blocks
                text_parts = [
                    block.text for block in response.content
                    if block.type == "text"
                ]
                reply_text = "\n".join(text_parts).strip()

                preview = reply_text.replace("\n", " ↵ ")
                if len(preview) > REPLY_LOG_PREVIEW:
                    preview = preview[:REPLY_LOG_PREVIEW] + "..."

                logger.info(
                    f"Agente {agent_name!r} resposta final | "
                    f"reply={preview!r} | tools_used={len(tool_calls_log)}"
                )

                return {
                    "text": reply_text,
                    "tool_calls": tool_calls_log,
                }

            # Loop excedeu o limite
            logger.warning(
                f"Agente {agent_name!r} excedeu max_iterations={MAX_TOOL_USE_ITERATIONS}"
            )
            return {
                "text": "Desculpa, tive um probleminha técnico. Pode repetir a mensagem?",
                "tool_calls": tool_calls_log,
            }

        except Exception as e:
            logger.exception(f"Erro ao chamar Claude (agent={agent_name}): {e}")
            return {
                "text": "Desculpe, tive um probleminha técnico aqui. Pode repetir a mensagem?",
                "tool_calls": tool_calls_log,
            }


claude = ClaudeService()

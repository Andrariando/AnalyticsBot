import json
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Any = Field(exclude=True)

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolCallRecord(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    output: Any
    execution_time_ms: float


class AgentResponse(BaseModel):
    content: str
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    iteration_count: int = 1
    execution_time_ms: float = 0.0
    model_used: str = ""


class BaseAgent:
    """Multi-turn cognitive agent equipped with autonomous tool calling."""

    def __init__(
        self,
        system_prompt: str,
        model_name: Optional[str] = None,
        tools: Optional[List[ToolDefinition]] = None,
        max_iterations: int = 10,
    ):
        self.system_prompt = system_prompt
        self.model_name = model_name or settings.SUPERVISOR_MODEL
        self.tools = tools or []
        self.max_iterations = max_iterations
        self._tool_map: Dict[str, ToolDefinition] = {t.name: t for t in self.tools}

        if settings.OPENAI_API_KEY:
            self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        else:
            self.openai_client = None

    def register_tool(self, tool: ToolDefinition) -> None:
        """Register a new tool dynamically."""
        self.tools.append(tool)
        self._tool_map[tool.name] = tool

    async def run_turn(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
    ) -> AgentResponse:
        """
        Executes an autonomous agent conversation turn with multi-step tool calling.
        """
        start_time = time.perf_counter()
        tool_records: List[ToolCallRecord] = []
        iteration = 0

        if not self.openai_client:
            raise ValueError("OpenAI API Key is not configured. Please set OPENAI_API_KEY in .env.")

        # Build message history with system prompt
        conversation_history: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt}
        ] + [m for m in messages if m.get("role") != "system"]

        openai_tools = [t.to_openai_tool() for t in self.tools] if self.tools else None

        while iteration < self.max_iterations:
            iteration += 1

            request_kwargs: Dict[str, Any] = {
                "model": self.model_name,
                "messages": conversation_history,
                "temperature": temperature,
            }
            if openai_tools:
                request_kwargs["tools"] = openai_tools
                request_kwargs["tool_choice"] = "auto"

            response = await self.openai_client.chat.completions.create(**request_kwargs)
            choice = response.choices[0]
            message = choice.message

            # Check if LLM wants to call tools
            if message.tool_calls:
                # Append assistant tool call message to history
                conversation_history.append(message.model_dump())

                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    raw_args = tool_call.function.arguments

                    try:
                        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        parsed_args = {}

                    t_start = time.perf_counter()
                    tool_def = self._tool_map.get(fn_name)

                    if not tool_def:
                        tool_output = {"error": f"Tool '{fn_name}' is not registered."}
                    else:
                        try:
                            # Execute handler (async or sync)
                            if asyncio_is_coroutine_callable(tool_def.handler):
                                tool_output = await tool_def.handler(**parsed_args)
                            else:
                                tool_output = tool_def.handler(**parsed_args)
                        except Exception as e:
                            logger.error(f"Error executing tool {fn_name}: {e}", exc_info=True)
                            tool_output = {"error": f"Tool execution failed: {str(e)}"}

                    t_duration_ms = (time.perf_counter() - t_start) * 1000.0

                    tool_records.append(
                        ToolCallRecord(
                            tool_name=fn_name,
                            arguments=parsed_args,
                            output=tool_output,
                            execution_time_ms=round(t_duration_ms, 2),
                        )
                    )

                    # Append tool result back to conversation
                    output_str = (
                        json.dumps(tool_output, default=str)
                        if not isinstance(tool_output, str)
                        else tool_output
                    )
                    conversation_history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": output_str,
                        }
                    )
            else:
                # Final response reached
                total_duration_ms = (time.perf_counter() - start_time) * 1000.0
                return AgentResponse(
                    content=message.content or "",
                    tool_calls=tool_records,
                    iteration_count=iteration,
                    execution_time_ms=round(total_duration_ms, 2),
                    model_used=self.model_name,
                )

        # Max iterations reached
        total_duration_ms = (time.perf_counter() - start_time) * 1000.0
        return AgentResponse(
            content="I reached the maximum number of analytical iterations for this turn. Here is my current progress and findings based on executed tools.",
            tool_calls=tool_records,
            iteration_count=iteration,
            execution_time_ms=round(total_duration_ms, 2),
            model_used=self.model_name,
        )


def asyncio_is_coroutine_callable(obj: Any) -> bool:
    import asyncio
    import inspect
    return asyncio.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )

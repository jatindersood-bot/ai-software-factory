"""
LLM client wrapper using the official OpenAI SDK.
Provides llm_json(system, user, validator?) -> (parsed_json, meta).
Supports repair loop on JSON parse or schema validation failure.
"""

import json
import os
import time
from typing import Any, Callable, Dict, Tuple

from openai import OpenAI

MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
API_KEY = os.getenv("LLM_API_KEY")

if not API_KEY:
    raise RuntimeError("LLM_API_KEY is not set")

client = OpenAI(api_key=API_KEY)

MAX_REPAIR_ATTEMPTS = 2


def llm_json(
    system: str,
    user: str,
    validator: Callable[[Dict[str, Any]], Any] | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Call the model and return (parsed_json, meta).
    If validator is provided, run it on the parsed dict; on failure, retry with a repair prompt.
    Retry up to MAX_REPAIR_ATTEMPTS (2) times on JSON parse or validation errors.
    Meta includes repair_attempts and, on final failure, last_error.
    """
    repair_attempts = 0
    last_error: str | None = None
    last_raw: str | None = None
    start = time.time()
    user_msg = user
    schema_instruction = "Return ONLY valid JSON matching the requested schema. No markdown, no explanation."

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                temperature=TEMPERATURE,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
            )

            content = response.choices[0].message.content
            last_raw = content
            parsed = json.loads(content)

            if validator is not None:
                validator(parsed)

            latency = int((time.time() - start) * 1000)
            usage_obj = getattr(response, "usage", None)
            usage = None
            if usage_obj:
                usage = {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                    "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                    "total_tokens": getattr(usage_obj, "total_tokens", None),
                }
            meta = {
                "provider": "openai",
                "model": MODEL,
                "latency_ms": latency,
                "retries": repair_attempts,
                "usage": usage,
            }
            return parsed, meta

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            repair_attempts += 1
            if attempt >= MAX_REPAIR_ATTEMPTS:
                latency_ms = int((time.time() - start) * 1000)
                exc = RuntimeError(
                    f"LLM JSON generation failed after {repair_attempts} repair attempts: {last_error}"
                )
                exc.meta = {
                    "provider": "openai",
                    "model": str(MODEL),
                    "latency_ms": latency_ms,
                    "retries": repair_attempts,
                    "repair_attempts": repair_attempts,
                    "last_error": last_error,
                    "usage": None,
                }
                exc.last_raw = last_raw
                raise exc from e
            user_msg = (
                f"{user}\n\n---\nPrevious response (invalid JSON):\n{last_raw or '(none)'}\n\n"
                f"Error: {last_error}\n\n{schema_instruction}"
            )
        except Exception as e:
            last_error = str(e)
            repair_attempts += 1
            if attempt >= MAX_REPAIR_ATTEMPTS:
                latency_ms = int((time.time() - start) * 1000)
                exc = RuntimeError(
                    f"LLM JSON generation failed after {repair_attempts} repair attempts: {last_error}"
                )
                exc.meta = {
                    "provider": "openai",
                    "model": str(MODEL),
                    "latency_ms": latency_ms,
                    "retries": repair_attempts,
                    "repair_attempts": repair_attempts,
                    "last_error": last_error,
                    "usage": None,
                }
                exc.last_raw = last_raw
                raise exc from e
            user_msg = (
                f"{user}\n\n---\nPrevious response:\n{last_raw or '(none)'}\n\n"
                f"Validation/parse error: {last_error}\n\n{schema_instruction}"
            )

    raise RuntimeError(f"LLM JSON generation failed after retries: {last_error}")

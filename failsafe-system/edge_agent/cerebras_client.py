import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from cerebras.cloud.sdk import Cerebras

from config import settings

logger = logging.getLogger(__name__)

PRINT_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "print_status": {
            "type": "string",
            "enum": ["nominal", "critical_failure"],
        },
        "issue_detected": {"type": "boolean"},
        "analysis": {"type": "string"},
    },
    "required": ["print_status", "issue_detected", "analysis"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a 3D printer vision safety monitor. Inspect the webcam image of an "
    "active Bambu Lab A1 print bed. Detect spaghetti, detached prints, severe "
    "layer shifts, nozzle collisions, fire hazards, or other critical failures. "
    "Return only structured JSON matching the schema."
)


@dataclass
class VisionAnalysis:
    print_status: str
    issue_detected: bool
    analysis: str
    time_info: dict[str, Any]
    raw_content: str


class CerebrasVisionClient:
    def __init__(
        self,
        api_key: str = settings.cerebras_api_key,
        model: str = settings.cerebras_model,
    ) -> None:
        if not api_key:
            raise ValueError("CEREBRAS_API_KEY is required")

        self.model = model
        self._client = Cerebras(api_key=api_key)

    def analyze_frame(self, image_base64: str) -> Optional[VisionAnalysis]:
        started = time.perf_counter()
        image_url = f"data:image/jpeg;base64,{image_base64}"

        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Analyze this live print bed image. "
                                    "Set print_status to critical_failure only for "
                                    "actionable emergencies."
                                ),
                            },
                        ],
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "print_analysis",
                        "strict": True,
                        "schema": PRINT_ANALYSIS_SCHEMA,
                    },
                },
                max_completion_tokens=256,
            )
        except Exception as exc:
            logger.error("Cerebras inference failed: %s", exc)
            return None

        content = completion.choices[0].message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.error("Cerebras returned non-JSON content: %s", content)
            return None

        time_info = self._extract_time_info(completion, started)
        return VisionAnalysis(
            print_status=str(parsed.get("print_status", "nominal")),
            issue_detected=bool(parsed.get("issue_detected", False)),
            analysis=str(parsed.get("analysis", "")),
            time_info=time_info,
            raw_content=content,
        )

    def _extract_time_info(self, completion: Any, started: float) -> dict[str, Any]:
        time_info: dict[str, Any] = {}

        if hasattr(completion, "time_info") and completion.time_info is not None:
            if hasattr(completion.time_info, "model_dump"):
                time_info = completion.time_info.model_dump()
            elif isinstance(completion.time_info, dict):
                time_info = dict(completion.time_info)

        end_to_end = time.perf_counter() - started
        time_info.setdefault("end_to_end_latency", round(end_to_end, 4))

        usage = getattr(completion, "usage", None)
        if usage is not None:
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            completion_time = float(time_info.get("completion_time") or 0.0)
            if completion_time > 0 and completion_tokens > 0:
                time_info.setdefault(
                    "tokens_per_second",
                    round(completion_tokens / completion_time, 2),
                )

        prompt_time = float(time_info.get("prompt_time") or 0.0)
        if prompt_time > 0:
            time_info.setdefault("time_to_first_token", round(prompt_time, 4))

        return time_info

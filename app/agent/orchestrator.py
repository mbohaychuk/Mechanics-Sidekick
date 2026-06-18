from __future__ import annotations

import json
from collections.abc import Iterator

from app.agent.provider import ChatProvider, ToolCall
from app.agent.tools import SEARCH_MANUALS_TOOL, execute_search_manuals
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.retrieval_service import RetrievalService

SYSTEM_PROMPT = (
    "You are Mechanic Sidekick, an expert assistant for automotive repair and maintenance. "
    "The vehicle is: {vehicle}. "
    "Use the search_manuals tool to look up specifications, torque values, fluid types, and "
    "procedures in the uploaded service manuals before answering factual questions. Never invent "
    "specs or procedures — if the manuals do not cover it, say so plainly. Keep answers concise and "
    "mechanic-friendly, and cite the source filename and page for any specification you give."
)


class AgentOrchestrator:
    def __init__(
        self,
        chat_repo: ChatRepository,
        job_repo: JobRepository,
        vehicle_repo: VehicleRepository,
        doc_repo: DocumentRepository,
        retrieval: RetrievalService,
        provider: ChatProvider,
        recent_messages_limit: int = 6,
        max_iters: int = 6,
    ) -> None:
        self._chat_repo = chat_repo
        self._job_repo = job_repo
        self._vehicle_repo = vehicle_repo
        self._doc_repo = doc_repo
        self._retrieval = retrieval
        self._provider = provider
        self._recent_limit = recent_messages_limit
        self._max_iters = max_iters

    def run(self, job_id: int, user_message: str) -> Iterator[dict]:
        job = self._job_repo.get_by_id(job_id)
        if job is None:
            yield {"type": "error", "detail": f"Job {job_id} not found"}
            return
        vehicle = self._vehicle_repo.get_by_id(job.vehicle_id)
        if vehicle is None:
            yield {"type": "error", "detail": f"Vehicle {job.vehicle_id} not found"}
            return

        recent = self._chat_repo.list_by_job(job_id, limit=self._recent_limit)
        self._chat_repo.create(job_id=job_id, role="user", content=user_message)

        vehicle_label = f"{vehicle.year} {vehicle.make} {vehicle.model}, engine {vehicle.engine}"
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(vehicle=vehicle_label)},
            {"role": "system", "content": f"Current job: {job.title}"},
        ]
        for m in recent:
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_message})

        tools = [SEARCH_MANUALS_TOOL]
        sources: list[dict] = []

        for _ in range(self._max_iters):
            turn = None
            for ev in self._provider.stream_turn(messages, tools):
                if ev["type"] == "token":
                    yield ev
                elif ev["type"] == "turn":
                    turn = ev["turn"]
            if turn is None:
                break

            if turn.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.text or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                            }
                            for tc in turn.tool_calls
                        ],
                    }
                )
                for tc in turn.tool_calls:
                    yield {"type": "tool_call", "name": tc.name, "arguments": tc.arguments}
                    result = self._execute(tc, job.vehicle_id)
                    if tc.name == "search_manuals":
                        sources.extend(result["sources"])
                    yield {"type": "tool_result", "name": tc.name}
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result["model_text"]}
                    )
                continue

            final = turn.text or ""
            if sources:
                yield {"type": "sources", "sources": sources}
            self._chat_repo.create(
                job_id=job_id, role="assistant", content=final, sources_json=json.dumps(sources)
            )
            yield {"type": "done"}
            return

        fallback = "I was not able to complete this within the allowed number of steps."
        self._chat_repo.create(
            job_id=job_id, role="assistant", content=fallback, sources_json=json.dumps(sources)
        )
        yield {"type": "error", "detail": "max_iterations_reached"}
        yield {"type": "done"}

    def _execute(self, tc: ToolCall, vehicle_id: int) -> dict:
        if tc.name == "search_manuals":
            return execute_search_manuals(
                self._retrieval, self._doc_repo, vehicle_id, tc.arguments.get("query", "")
            )
        return {"sources": [], "model_text": f"Unknown tool: {tc.name}"}

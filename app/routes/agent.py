from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import json

from app.dependencies import get_agent_service
from app.schemas.result import Result
from app.schemas.chat import ChatRequest
from app.services.agent_service import AgentService

router = APIRouter(tags=["agent"])


@router.get("/health")
def health_check(
    session_id: str,
    agent_service: AgentService = Depends(get_agent_service),
) -> Result:
    return Result(data=agent_service.get_health_data(session_id), msg="success", code=200)


@router.post("/chat")
def chat(
    payload: ChatRequest,
    agent_service: AgentService = Depends(get_agent_service),
) -> StreamingResponse:
    session_id = payload.session_id

    def event_stream():
        try:
            for chunk in agent_service.stream_chat(payload.message, session_id):
                data = json.dumps({"response": chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except RuntimeError as exc:
            data = json.dumps({"detail": str(exc)}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

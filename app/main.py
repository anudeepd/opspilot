from dotenv import load_dotenv
load_dotenv()

import logging
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.models.schema import (
    TicketInput,
    OpsPilotResponse,
    AgentOutput,
    FailureType,
    ConfidenceLevel,
)
from app.agent.tools import load_config, Tools
from app.agent.graph import run_opspilot

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

config = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config
    config = load_config("config.yaml")
    Tools.initialize(config)
    await Tools.initialize_mcp_tools()

    logger.info("OpsPilot service started")
    yield
    logger.info("OpsPilot service stopped")


app = FastAPI(
    title="OpsPilot",
    description="Agentic L1 Support Intelligence for IBM TWS Job Failures",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "opspilot"}


@app.get("/vector-db/count")
async def get_vector_db_count():
    if Tools.vector_db:
        return {"count": Tools.vector_db.get_count()}
    return {"count": 0, "status": "vector db not initialized"}


@app.post("/ichamp/sync")
async def sync_ichamp_tickets(start_date: str, end_date: str):
    if not Tools.ichamp_client or not Tools.vector_db:
        return {"error": "iChamp client or vector DB not initialized"}

    tickets = Tools.ichamp_client.fetch_tickets(start_date, end_date)
    if tickets:
        Tools.vector_db.add_documents(tickets)
        return {"status": "synced", "tickets_added": len(tickets)}
    return {"status": "no tickets found"}


@app.post("/vector-db/clear")
async def clear_vector_db():
    if Tools.vector_db:
        Tools.vector_db.clear()
        return {"status": "cleared"}
    return {"error": "vector db not initialized"}


@app.post("/vector-db/add")
async def add_documents_to_vector_db(tickets: list[dict]):
    if Tools.vector_db:
        Tools.vector_db.add_documents(tickets)
        return {"status": "added", "count": len(tickets)}
    return {"error": "vector db not initialized"}


@app.post("/investigate", response_model=OpsPilotResponse)
async def investigate_ticket(ticket: TicketInput):
    start_time = time.time()

    request_id = str(uuid.uuid4())

    logger.info(f"Processing ticket {ticket.ticket_id} for job {ticket.job_name}")

    try:
        result = await run_opspilot(
            ticket_id=ticket.ticket_id,
            job_name=ticket.job_name,
            description=ticket.description,
            tws_log=ticket.tws_log,
            script_name=ticket.script_name,
            command=ticket.command,
            request_id=request_id,
        )

        processing_time_ms = int((time.time() - start_time) * 1000)

        rec = result.get("recommendation", {})

        failure_type_str = result.get("failure_type", "unknown")
        try:
            failure_type = FailureType(failure_type_str)
        except ValueError:
            failure_type = FailureType.UNKNOWN

        confidence_str = rec.get("confidence", "low")
        try:
            confidence = ConfidenceLevel(confidence_str)
        except ValueError:
            confidence = ConfidenceLevel.LOW

        log_analysis_status = result.get("log_analysis_status", "")
        agent_outputs = [
            AgentOutput(
                agent_name="historical_search",
                status="completed",
                findings={"results_count": len(result.get("historical_results", []))},
            ),
            AgentOutput(
                agent_name="bitbucket_context",
                status="completed",
                findings={"config_found": result.get("job_config") is not None},
            ),
            AgentOutput(
                agent_name="edge_node_script",
                status="completed",
                findings={
                    "script_retrieved": result.get("edge_node_result") is not None
                },
            ),
            AgentOutput(
                agent_name="jira_intelligence",
                status="completed",
                findings={"tickets_found": len(result.get("jira_results", []))},
            ),
            AgentOutput(
                agent_name="log_analysis",
                status="completed" if result.get("log_analysis") else "skipped",
                findings={"status": log_analysis_status},
            ),
            AgentOutput(
                agent_name="resolution_synthesis", status="completed", findings={}
            ),
        ]

        response = OpsPilotResponse(
            request_id=request_id,
            ticket_id=ticket.ticket_id,
            job_name=ticket.job_name,
            failure_type=failure_type,
            root_cause=rec.get("root_cause", "Unknown"),
            recommended_actions=rec.get("recommended_actions", []),
            confidence=confidence,
            evidence=rec.get("evidence", {}),
            escalation_needed=rec.get("escalation_needed", False),
            processing_time_ms=processing_time_ms,
            log_analysis=result.get("log_analysis"),
            agent_outputs=agent_outputs,
        )

        return response

    except Exception as e:
        logger.error(f"Error processing ticket: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

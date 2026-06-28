import logging
from typing import TypedDict, List, Optional, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent import nodes

logger = logging.getLogger(__name__)


class OpsPilotState(TypedDict):
    request_id: str
    ticket_id: str
    job_name: str
    description: str
    tws_log: str
    script_name: Optional[str]
    command: Optional[str]

    failure_type: Optional[str]
    needs_edge_node: bool

    historical_results: List[Any]
    historical_analysis: str

    job_config: Optional[Any]
    bitbucket_analysis: str

    edge_node_result: Optional[Any]
    edge_node_analysis: str

    jira_results: List[Any]
    jira_analysis: str

    log_analysis: Optional[str]
    log_analysis_status: str

    recommendation: Optional[Any]
    synthesis_analysis: str


def create_opspilot_graph() -> StateGraph:
    workflow = StateGraph(OpsPilotState)

    workflow.add_node("orchestrator", nodes.orchestrator_node)
    workflow.add_node("historical_search", nodes.historical_search_node)
    workflow.add_node("bitbucket_context", nodes.bitbucket_context_node)
    workflow.add_node("edge_node_script", nodes.edge_node_script_node)
    workflow.add_node("jira_intelligence", nodes.jira_intelligence_node)
    workflow.add_node("log_analysis", nodes.log_analysis_node)
    workflow.add_node("resolution_synthesis", nodes.resolution_synthesis_node)

    workflow.set_entry_point("orchestrator")

    workflow.add_edge("orchestrator", "historical_search")
    workflow.add_edge("orchestrator", "bitbucket_context")
    workflow.add_edge("orchestrator", "jira_intelligence")

    workflow.add_edge("historical_search", "edge_node_script")

    # All parallel branches converge at log_analysis before synthesis
    workflow.add_edge("bitbucket_context", "log_analysis")
    workflow.add_edge("edge_node_script", "log_analysis")
    workflow.add_edge("jira_intelligence", "log_analysis")

    workflow.add_edge("log_analysis", "resolution_synthesis")
    workflow.add_edge("resolution_synthesis", END)

    return workflow


def compile_graph() -> Any:
    workflow = create_opspilot_graph()
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


ops_agent = compile_graph()


async def run_opspilot(
    ticket_id: str,
    job_name: str,
    description: str,
    tws_log: str,
    script_name: str = None,
    command: str = None,
    request_id: str = None,
) -> OpsPilotState:
    import uuid

    if request_id is None:
        request_id = str(uuid.uuid4())

    initial_state: OpsPilotState = {
        "request_id": request_id,
        "ticket_id": ticket_id,
        "job_name": job_name,
        "description": description,
        "tws_log": tws_log,
        "script_name": script_name,
        "command": command,
        "failure_type": None,
        "needs_edge_node": False,
        "historical_results": [],
        "historical_analysis": "",
        "job_config": None,
        "bitbucket_analysis": "",
        "edge_node_result": None,
        "edge_node_analysis": "",
        "jira_results": [],
        "jira_analysis": "",
        "log_analysis": None,
        "log_analysis_status": "",
        "recommendation": None,
        "synthesis_analysis": "",
    }

    result = await ops_agent.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": request_id}},
    )

    return result

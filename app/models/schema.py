from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class FailureType(str, Enum):
    JOB_NOT_TRIGGER = "job_not_trigger"
    CPU_HIGH = "cpu_high"
    LONG_RUNNING = "long_running"
    UPSTREAM_DEPENDENCY = "upstream_dependency"
    OOM = "oom"
    PERMISSION_ERROR = "permission_error"
    PYTHON_VERSION = "python_version"
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class TicketInput(BaseModel):
    ticket_id: str = Field(..., description="iChamp ticket ID")
    job_name: str = Field(..., description="IBM TWS job name")
    description: str = Field(..., description="Ticket description")
    tws_log: str = Field(..., description="IBM TWS log content")
    script_name: Optional[str] = Field(None, description="Script filename e.g. DBS_JOB.py")
    command: Optional[str] = Field(None, description="Full TWS JOBCMD invocation")


class HistoricalTicket(BaseModel):
    ticket_id: str
    job_name: str
    description: str
    resolution: str
    resolved_by: str
    resolved_at: str
    similarity_score: float = 0.0
    script_name: Optional[str] = None
    failure_type: Optional[str] = None


class JobConfig(BaseModel):
    job_name: str
    trigger_command: str
    dependencies: List[str] = Field(default_factory=list)
    schedule: Optional[str] = None
    script_path: Optional[str] = None
    config_file_path: Optional[str] = None


class EdgeNodeScript(BaseModel):
    node_name: str
    script_content: str
    environment_vars: dict = Field(default_factory=dict)
    file_permissions: Optional[str] = None


class JiraTicket(BaseModel):
    ticket_key: str
    summary: str
    description: str
    status: str
    fix_details: Optional[str] = None
    root_cause: Optional[str] = None
    workaround: Optional[str] = None
    comments: List[dict] = Field(default_factory=list)


class ResolutionRecommendation(BaseModel):
    root_cause: str
    recommended_actions: List[str]
    confidence: ConfidenceLevel
    evidence: dict = Field(default_factory=dict)
    escalation_needed: bool = False
    escalation_reason: Optional[str] = None


class AgentOutput(BaseModel):
    agent_name: str
    status: str
    findings: dict = Field(default_factory=dict)
    error: Optional[str] = None


class OpsPilotResponse(BaseModel):
    request_id: str
    ticket_id: str
    job_name: str
    failure_type: FailureType
    root_cause: str
    recommended_actions: List[str]
    confidence: ConfidenceLevel
    evidence: dict
    escalation_needed: bool
    processing_time_ms: int
    log_analysis: Optional[str] = None
    agent_outputs: List[AgentOutput] = Field(default_factory=list)


class HistoricalSearchOutput(BaseModel):
    similar_tickets: List[HistoricalTicket]
    analysis: str


class BitbucketContextOutput(BaseModel):
    job_config: Optional[JobConfig]
    analysis: str
    needs_edge_node: bool = False
    reason: Optional[str] = None


class EdgeNodeOutput(BaseModel):
    script: Optional[EdgeNodeScript]
    analysis: str


class JiraIntelligenceOutput(BaseModel):
    related_tickets: List[JiraTicket]
    analysis: str


class SynthesisOutput(BaseModel):
    recommendation: ResolutionRecommendation
    synthesis: str

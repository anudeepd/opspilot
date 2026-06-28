import json
import logging
import os
from typing import Any, Dict, Optional

async def _stream_agent(agent, messages: dict, agent_name: str) -> tuple:
    """Run agent with streaming, log each tool call and response.

    Returns:
        (final_content: str, tool_calls: list[dict])
        tool_calls entries: {"name": str, "input": dict}
    """
    final_content = ""
    tool_calls = []
    async for event in agent.astream_events(messages, version="v2"):
        kind = event["event"]
        name = event.get("name", "")
        if kind == "on_tool_start":
            tool_input = event["data"].get("input", {})
            logger.info(f"[{agent_name}] → {name}: {tool_input}")
            tool_calls.append({"name": name, "input": tool_input})
        elif kind == "on_tool_end":
            output = str(event["data"].get("output", ""))
            logger.info(f"[{agent_name}] ← {name}: {output[:300]}")
        elif kind == "on_chat_model_end":
            output = event["data"].get("output")
            if hasattr(output, "content") and output.content:
                final_content = output.content
    return final_content, tool_calls

from app.models.schema import (
    FailureType,
    ConfidenceLevel,
    HistoricalTicket,
    EdgeNodeScript,
    ResolutionRecommendation,
)

logger = logging.getLogger(__name__)


def classify_failure_type(tws_log: str, description: str) -> FailureType:
    log_lower = tws_log.lower()
    desc_lower = description.lower()
    combined = f"{log_lower} {desc_lower}"

    if "not submitted" in combined or "not trigger" in combined or "hold state" in combined:
        # Check predecessor/HOLD first — more specific than upstream
        if "predecessor" in combined or "hold state" in combined or "awsbhv026e" in combined:
            return FailureType.UPSTREAM_DEPENDENCY
        return FailureType.JOB_NOT_TRIGGER

    elif any(x in combined for x in ["outofmemory", "java heap", "oom", "executor lost",
                                       "gc overhead", "heap space", "fetchfailedexception"]):
        return FailureType.OOM

    elif any(x in combined for x in ["permission denied", "rc=126", "rc=127",
                                       "exit code 126", "exit code 127", "abend rc=126"]):
        return FailureType.PERMISSION_ERROR

    elif (any(x in combined for x in ["syntaxerror", "invalid syntax", "modulenotfounderror",
                                        "importerror", "syntax error"])
          or "/usr/bin/python " in combined):
        return FailureType.PYTHON_VERSION

    elif "cpu" in combined or "cpu high" in desc_lower or "cpu usage" in log_lower:
        return FailureType.CPU_HIGH

    elif (
        "exceeded" in combined
        or "long-running" in combined
        or "breach" in combined
        or "wallclock" in combined
    ):
        return FailureType.LONG_RUNNING

    elif (
        "predecessor" in combined
        or "upstream" in combined
        or "did not complete" in combined
        or "awsbhv026e" in combined
    ):
        return FailureType.UPSTREAM_DEPENDENCY

    else:
        return FailureType.UNKNOWN


def extract_job_name(tws_log: str, description: str) -> Optional[str]:
    import re

    patterns = [
        r"job[:\s]+([A-Z_]+)",
        r"Job[:\s]+([A-Z_]+)",
        r"DBS_[A-Z_]+",
    ]

    for pattern in patterns:
        match = re.search(pattern, f"{tws_log} {description}")
        if match:
            return match.group(0).split(":")[-1].strip()

    return None


async def historical_search_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from app.agent.tools import Tools

    job_name = state.get("job_name", "")
    script_name = state.get("script_name")
    tws_log = state.get("tws_log", "")
    description = state.get("description", "")

    logger.info(f"Historical Search Agent: Searching for job {job_name}")

    vector_db = Tools.vector_db
    if vector_db is None:
        return {
            "historical_results": [],
            "historical_analysis": "Vector DB not initialized",
        }

    query = f"{description} {tws_log}"
    results = vector_db.search(query, job_name=job_name, script_name=script_name, top_k=5)

    tickets = []
    for r in results:
        tickets.append(
            HistoricalTicket(
                ticket_id=r.get("ticket_id", ""),
                job_name=r.get("job_name", ""),
                description=r.get("description", ""),
                resolution=r.get("resolution", ""),
                resolved_by=r.get("resolved_by", "unknown"),
                resolved_at=r.get("resolved_at", "2024-01-01"),
                similarity_score=r.get("similarity_score", 0.0),
                script_name=r.get("script_name"),
                failure_type=r.get("failure_type"),
            )
        )

    return {
        "historical_results": [t.model_dump() for t in tickets],
        "historical_analysis": (
            f"Found {len(tickets)} similar tickets"
            if tickets
            else "No historical matches found"
        ),
    }


async def bitbucket_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from app.agent.tools import Tools

    job_name = state.get("job_name", "")
    script_name = state.get("script_name") or f"{job_name}.py"
    logger.info(f"Bitbucket Context Agent: Fetching config for {job_name}")

    config = Tools.config or {}
    run_mode = config.get("run_mode", "production")

    # Local mode: serve script from edge node dummy_scripts directory
    if run_mode == "local":
        edge_node_pool = Tools.edge_node_pool
        node = edge_node_pool.find_node_by_job(job_name) if edge_node_pool else None
        result = node.get_script(script_name) if node else None
        if not result and script_name.endswith(".py"):
            result = node.get_script(script_name.replace(".py", ".sh")) if node else None
        content = result.get("content", f"Script '{script_name}' not found in local dummy_scripts.") if result else f"Script '{script_name}' not found in local dummy_scripts."
        logger.info(f"Bitbucket (local mode): served {script_name} from edge node")
        return {
            "job_config": {"job_name": job_name, "script_name": script_name, "content": content},
            "bitbucket_analysis": content,
        }

    # Production mode: use MCP
    from langgraph.prebuilt import create_react_agent
    from ada_genai.langchain import ChatVertexAI
    from langchain_core.messages import HumanMessage, SystemMessage

    bitbucket_cfg = config.get("bitbucket", {})
    project = bitbucket_cfg.get("project", "")
    repo_slug = bitbucket_cfg.get("repo_slug", "")
    repo_path = bitbucket_cfg.get("repo_path", "jobs")
    branch = bitbucket_cfg.get("default_branch", "main")
    llm_model = config.get("llm", {}).get("model", "gemini-2.5-flash")

    script_hint = f"The script filename is known to be '{script_name}'. Look for this file first." if script_name else ""

    try:
        tools = Tools.bitbucket_tools
        if not tools:
            raise RuntimeError("Bitbucket MCP tools not initialized")
        llm = ChatVertexAI(model_name=llm_model)
        agent = create_react_agent(llm, tools)

        content, tool_calls = await _stream_agent(agent, {
            "messages": [
                SystemMessage(content=(
                    "You are an assistant that uses Bitbucket MCP tools to locate and fetch job scripts. "
                    "You can only list files and get file content by full path. "
                    "Always list files first to discover the correct path, then fetch the content."
                )),
                HumanMessage(content=(
                    f"{script_hint} "
                    f"Find and fetch the script for job '{job_name}' in project '{project}', "
                    f"repo '{repo_slug}', branch '{branch}'. "
                    f"Start by listing files under '{repo_path}' to find the file that corresponds to '{job_name}' "
                    f"(the filename may be lowercase or have a different casing). "
                    f"Once you identify the correct file path, retrieve its content."
                )),
            ]
        }, "Bitbucket")

        # Extract resolved path from the LAST get_repo_file_content call —
        # agent may attempt wrong paths first before finding the correct one.
        resolved_path = None
        for tc in reversed(tool_calls):
            if "get_repo_file_content" in tc.get("name", ""):
                inp = tc.get("input", {})
                resolved_path = inp.get("file_path") or inp.get("path") or inp.get("filePath")
                if resolved_path:
                    break
        resolved_name = resolved_path.split("/")[-1] if resolved_path else script_name

        return {
            "job_config": {"job_name": job_name, "script_name": resolved_name, "resolved_path": resolved_path, "content": content},
            "bitbucket_analysis": content,
        }
    except Exception as e:
        logger.error(f"Bitbucket MCP error: {e}")
        return {
            "job_config": None,
            "bitbucket_analysis": f"Failed to fetch Bitbucket config: {e}",
        }


async def edge_node_script_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from app.agent.tools import Tools

    job_name = state.get("job_name", "")
    needs_edge = state.get("needs_edge_node", False)

    if not needs_edge:
        return {
            "edge_node_result": None,
            "edge_node_analysis": "Edge node not needed per orchestrator decision",
        }

    logger.info(f"Edge Node Agent: Fetching script for {job_name}")

    edge_node_pool = Tools.edge_node_pool
    if edge_node_pool is None:
        return {
            "edge_node_result": None,
            "edge_node_analysis": "Edge node pool not initialized",
        }

    node = edge_node_pool.find_node_by_job(job_name)
    if node is None:
        return {
            "edge_node_result": None,
            "edge_node_analysis": f"No edge node found for job {job_name}",
        }

    target_script = state.get("script_name") or f"{job_name}.py"
    script_result = node.get_script(target_script)

    if script_result:
        edge_script = EdgeNodeScript(
            node_name=node.name,
            script_content=script_result.get("content", ""),
            environment_vars=script_result.get("env", {}),
            file_permissions=script_result.get("permissions", "rwxr-xr-x"),
        )
        return {
            "edge_node_result": edge_script.model_dump(),
            "edge_node_analysis": f"Retrieved live script from {node.name}",
        }
    else:
        return {
            "edge_node_result": None,
            "edge_node_analysis": "Could not retrieve script from edge node",
        }


async def jira_intelligence_node(state: Dict[str, Any]) -> Dict[str, Any]:
    from app.agent.tools import Tools

    job_name = state.get("job_name", "")
    failure_type = state.get("failure_type", "unknown")
    logger.info(f"Jira Intelligence Agent: Searching for {job_name}")

    config = Tools.config or {}
    run_mode = config.get("run_mode", "production")

    # Local mode: load from dummy_jira_tickets.json
    if run_mode == "local":
        try:
            jira_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "../../data/dummy_jira_tickets.json"
            )
            with open(jira_path) as f:
                all_tickets = json.load(f)
            job_lower = job_name.lower()
            matched = [
                t for t in all_tickets
                if job_lower in t.get("summary", "").lower()
                or job_lower in t.get("description", "").lower()
                or job_lower in " ".join(t.get("labels", [])).lower()
            ]
            logger.info(f"Jira (local mode): found {len(matched)} tickets for {job_name}")
            return {
                "jira_results": matched[:3],
                "jira_analysis": f"Found {len(matched)} local Jira tickets for {job_name}",
            }
        except Exception as e:
            logger.error(f"Jira local load error: {e}")
            return {"jira_results": [], "jira_analysis": f"Could not load local Jira data: {e}"}

    # Production mode: use MCP
    from langgraph.prebuilt import create_react_agent
    from ada_genai.langchain import ChatVertexAI
    from langchain_core.messages import HumanMessage, SystemMessage

    jira_cfg = config.get("jira", {})
    project_key = jira_cfg.get("project_key", "")
    jira_url = config.get("mcp", {}).get("jira", {}).get("env", {}).get("JIRA_URL", "")
    llm_model = config.get("llm", {}).get("model", "gemini-2.5-flash")

    try:
        tools = Tools.jira_tools
        if not tools:
            raise RuntimeError("Jira MCP tools not initialized")
        llm = ChatVertexAI(model_name=llm_model)
        agent = create_react_agent(llm, tools)

        content, _ = await _stream_agent(agent, {
            "messages": [
                SystemMessage(content="You are an assistant that uses Jira MCP tools to search for tickets related to job failures."),
                HumanMessage(content=(
                    f"On Jira instance '{jira_url}', search project '{project_key}' "
                    f"for tickets related to job '{job_name}' with failure type '{failure_type}'. "
                    f"Return key details about any relevant tickets found, including comments if available."
                )),
            ]
        }, "Jira")
        import re as _re
        extracted_keys = _re.findall(r'\b[A-Z]{2,10}-\d+\b', content)
        jira_results = (
            [{"key": k, "summary": f"Jira ticket {k}"} for k in extracted_keys]
            if extracted_keys
            else [{"summary": content}]
        )
        return {
            "jira_results": jira_results,
            "jira_analysis": content,
        }
    except Exception as e:
        logger.error(f"Jira MCP error: {e}")
        return {
            "jira_results": [],
            "jira_analysis": f"Failed to fetch Jira tickets: {e}",
        }


async def log_analysis_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LLM cross-analysis: script + TWS log + historical + jira → specific line-level diagnosis."""
    from app.agent.tools import Tools

    job_name  = state.get("job_name", "")
    tws_log   = state.get("tws_log", "")
    desc      = state.get("description", "")
    fail_type = state.get("failure_type", "unknown")
    script_name = state.get("script_name", "")

    # Prefer bitbucket content; fall back to edge node
    job_config  = state.get("job_config") or {}
    edge_result = state.get("edge_node_result") or {}
    script_content = (
        job_config.get("content")
        or edge_result.get("script_content")
        or "Script not available"
    )
    # Truncate to avoid token limit
    script_snippet = script_content[:3000] + ("…" if len(script_content) > 3000 else "")

    # Summarise historical tickets (top 3)
    historical = state.get("historical_results", [])
    hist_lines = [
        f"- {t.get('ticket_id','?')}: {t.get('description','')[:120]} "
        f"→ {t.get('resolution','')[:160]}"
        for t in historical[:3]
    ]
    hist_block = "\n".join(hist_lines) if hist_lines else "None found"

    # Summarise Jira tickets (top 3)
    jira = state.get("jira_results", [])
    jira_lines = [
        f"- {t.get('key') or t.get('ticket_key','?')}: "
        f"{t.get('summary','')[:120]} "
        f"→ {t.get('fix_details') or t.get('root_cause','')[:160]}"
        for t in jira[:3]
    ]
    jira_block = "\n".join(jira_lines) if jira_lines else "None found"

    prompt = f"""You are a senior IBM TWS operations engineer. Diagnose this job failure precisely.

JOB: {job_name}  |  FAILURE TYPE: {fail_type}
DESCRIPTION: {desc}

=== TWS LOG ===
{tws_log}

=== SCRIPT: {script_name} ===
{script_snippet}

=== HISTORICAL SIMILAR INCIDENTS ===
{hist_block}

=== RELATED JIRA TICKETS ===
{jira_block}

Provide a concise diagnostic report with:
1. **Specific Root Cause** — exact line/function/query/config causing the failure. Reference line numbers from the script if visible.
2. **Key Log Signals** — the 2–3 most diagnostic lines from the TWS log and what they indicate.
3. **Immediate Fix** — the single most critical action to resolve this right now.
4. **Prevention** — one change to prevent recurrence.

Be precise. Reference actual content from the script and log. No fluff."""

    logger.info(f"Log Analysis: running LLM diagnosis for {job_name}")
    config = Tools.config or {}
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "vertexai")
    model    = llm_cfg.get("model", "gemini-2.5-flash")

    try:
        if provider == "vertexai":
            from ada_genai.langchain import ChatVertexAI
            from langchain_core.messages import HumanMessage
            llm      = ChatVertexAI(model_name=model, temperature=0.0)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            analysis = response.content
        else:
            import litellm
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            analysis = response.choices[0].message.content

        logger.info(f"Log Analysis: completed for {job_name}")
        return {"log_analysis": analysis, "log_analysis_status": "completed"}

    except Exception as e:
        logger.warning(f"Log Analysis: LLM unavailable ({e}) — skipping")
        return {"log_analysis": None, "log_analysis_status": f"unavailable: {e}"}


async def resolution_synthesis_node(state: Dict[str, Any]) -> Dict[str, Any]:
    job_name = state.get("job_name", "")
    failure_type = state.get("failure_type", FailureType.UNKNOWN)
    historical = state.get("historical_results", [])
    jira = state.get("jira_results", [])
    edge = state.get("edge_node_result")
    bitbucket = state.get("job_config", {})

    logger.info(f"Resolution Synthesis Agent: Creating recommendation for {job_name}")

    from app.agent.tools import Tools as _Tools
    cfg = _Tools.config or {}

    script_name_ref = (
        state.get("script_name")
        or (bitbucket.get("script_name") if bitbucket else None)
        or f"{job_name}.py"
    )

    # Bitbucket full path: workspace / repo_slug / resolved_path (or repo_path/script_name)
    bb_cfg        = cfg.get("bitbucket", {})
    bb_workspace  = cfg.get("mcp", {}).get("bitbucket", {}).get("env", {}).get("BITBUCKET_WORKSPACE", "")
    bb_repo       = bb_cfg.get("repo_slug", "")
    bb_path       = bb_cfg.get("repo_path", "")
    bb_branch     = bb_cfg.get("default_branch", "main")
    resolved_path = bitbucket.get("resolved_path") if bitbucket else None
    if bb_workspace and bb_repo:
        file_part = resolved_path or "/".join(filter(None, [bb_path, script_name_ref]))
        bb_full = f"{bb_workspace}/{bb_repo}/{file_part} @ {bb_branch}"
    else:
        bb_full = resolved_path or script_name_ref

    # Edge node full path: node_name (host:port) → scripts_path / script_name
    edge_node_cfg  = next(iter(cfg.get("edge_nodes", [])), {})
    edge_node_name = edge.get("node_name", "edge-node") if edge else ""
    edge_host      = edge_node_cfg.get("host", "")
    edge_port      = edge_node_cfg.get("port", "")
    edge_scripts   = edge_node_cfg.get("scripts_path", "").rstrip("/")
    if edge_host and edge_port:
        edge_addr = f"{edge_node_name} ({edge_host}:{edge_port})"
    else:
        edge_addr = edge_node_name
    edge_full = f"{edge_addr} \u2192 {edge_scripts}/{script_name_ref}" if edge else None

    evidence = {
        "historical_tickets": len(historical),
        "jira_tickets": len(jira),
        "edge_node_available": edge is not None,
        "bitbucket_config": bitbucket.get("job_name") is not None if bitbucket else False,
        # reference data surfaced in the UI
        "historical_ticket_ids": [t.get("ticket_id", "") for t in historical if t.get("ticket_id")],
        "jira_ticket_keys": [
            t.get("key") or t.get("ticket_key") or ""
            for t in jira
            if t.get("key") or t.get("ticket_key")
        ],
        "edge_node_ref": edge_full,
        "bitbucket_ref": bb_full if bitbucket and bitbucket.get("job_name") else None,
    }

    if failure_type in (FailureType.JOB_NOT_TRIGGER, FailureType.UPSTREAM_DEPENDENCY):
        root_cause = "Upstream predecessor job failed or stalled — current job could not start"
        actions = [
            "Verify upstream job status in TWS console",
            "Release any HOLD state on predecessor job",
            "Check source system availability",
            "Restart upstream job if blocked",
            "Monitor for auto-trigger on completion",
        ]
        confidence = ConfidenceLevel.HIGH if (historical or jira) else ConfidenceLevel.MODERATE

    elif failure_type == FailureType.CPU_HIGH:
        root_cause = "Database or batch job causing excessive CPU — likely unoptimised query or data volume spike"
        actions = [
            "Check DB slow query log for queries exceeding 30s",
            "Add missing indexes on high-cardinality filter columns",
            "Rewrite bulk INSERTs to use executemany() or batch mode",
            "Consider splitting workload with --subset or date-range flag",
            "Notify DBA to investigate connection pool settings",
        ]
        confidence = ConfidenceLevel.HIGH if historical else ConfidenceLevel.MODERATE

    elif failure_type == FailureType.LONG_RUNNING:
        root_cause = "Script scope expanded or data volume spike causing SLA breach"
        actions = [
            "Allow current run to complete if within acceptable window",
            "Check for --subset flag to split workload",
            "Notify dev team of unexpected data volume",
            "Review job schedule and SLA thresholds",
        ]
        confidence = ConfidenceLevel.HIGH if edge else ConfidenceLevel.MODERATE

    elif failure_type == FailureType.OOM:
        root_cause = "Spark executor out of memory — insufficient memory allocation or skewed data partition"
        actions = [
            "Increase spark.executor.memory (recommended: 4g–8g)",
            "Add repartition(200) before large DataFrame joins",
            "Avoid df.collect() on large datasets — write to storage instead",
            "Check for partition skew with df.groupBy(<key>).count()",
            "Review broadcast join hints — avoid broadcasting tables > 200MB",
        ]
        confidence = ConfidenceLevel.HIGH if historical else ConfidenceLevel.MODERATE

    elif failure_type == FailureType.PERMISSION_ERROR:
        root_cause = "Script or helper not executable — file permission or line-ending issue after deploy"
        actions = [
            "Run: chmod +x <script_name> on the failing script",
            "Run: file <script_name> — if output shows 'CRLF', run dos2unix <script_name>",
            "Verify deploy pipeline applies execute permissions post-copy",
            "Check child scripts called by the main script also have execute permissions",
        ]
        confidence = ConfidenceLevel.HIGH

    elif failure_type == FailureType.PYTHON_VERSION:
        root_cause = "Python version mismatch — script requires Python 3.8+ but TWS JOBCMD points to older interpreter"
        actions = [
            "Update TWS JOBCMD: replace /usr/bin/python with /usr/bin/python3",
            "Verify Python 3.8+ available on execution host: python3 --version",
            "Check that the correct virtualenv is activated in the TWS job environment",
            "Review script for walrus operator (:=) or f-strings that require Python 3.6+",
            "Install missing modules: pip3 install <module>",
        ]
        confidence = ConfidenceLevel.HIGH if historical else ConfidenceLevel.MODERATE

    else:
        root_cause = "Unable to determine root cause from available data — insufficient log information"
        actions = [
            "Review full job log on the execution host for additional error output",
            "Check TWS event log for ABEND details",
            "Contact the job owner / dev team with the full log",
            "Escalate to L2 support",
        ]
        confidence = ConfidenceLevel.LOW

    escalation_needed = confidence == ConfidenceLevel.LOW

    recommendation = ResolutionRecommendation(
        root_cause=root_cause,
        recommended_actions=actions,
        confidence=confidence,
        evidence=evidence,
        escalation_needed=escalation_needed,
        escalation_reason="Low confidence - manual review required"
        if escalation_needed
        else None,
    )

    return {
        "recommendation": recommendation.model_dump(),
        "synthesis_analysis": f"Generated resolution with {confidence.value} confidence",
    }


def orchestrator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    job_name = state.get("job_name", "")
    tws_log = state.get("tws_log", "")
    description = state.get("description", "")

    logger.info(f"Orchestrator: Analyzing failure for {job_name}")

    failure_type = classify_failure_type(tws_log, description)

    if not job_name:
        job_name = extract_job_name(tws_log, description) or "UNKNOWN"

    needs_edge_node = True

    logger.info(f"Orchestrator: Determined failure type = {failure_type.value}")

    return {
        "failure_type": failure_type.value,
        "job_name": job_name,
        "needs_edge_node": needs_edge_node,
    }

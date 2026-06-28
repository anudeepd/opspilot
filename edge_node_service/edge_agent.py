"""
Edge Node Agent Service
Runs on RHEL8 edge nodes to serve scripts and logs to OpsPilot
"""

import os
import logging
from flask import Flask, jsonify, request

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

SCRIPTS_PATH = os.environ.get("SCRIPTS_PATH", "/opt/tws/scripts")
LOGS_PATH = os.environ.get("LOGS_PATH", "/var/log/tws")


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {"status": "healthy", "node": os.environ.get("NODE_NAME", "unknown")}
    )


@app.route("/api/script", methods=["GET"])
def get_script():
    script_name = request.args.get("name")
    if not script_name:
        return jsonify({"error": "Script name required"}), 400

    if not script_name.endswith((".py", ".sh")):
        script_name = f"{script_name}.py"

    scripts_path = request.args.get("scripts_path", SCRIPTS_PATH)
    script_path = os.path.join(scripts_path, script_name)

    if not os.path.exists(script_path):
        logger.warning(f"Script not found: {script_path}")
        return jsonify({"error": "Script not found"}), 404

    try:
        with open(script_path, "r") as f:
            content = f.read()

        import stat

        file_stat = os.stat(script_path)
        permissions = oct(file_stat.st_mode)[-3:]

        return jsonify(
            {
                "name": script_name,
                "path": script_path,
                "content": content,
                "permissions": permissions,
                "size": file_stat.st_size,
                "modified": file_stat.st_mtime,
            }
        )
    except Exception as e:
        logger.error(f"Error reading script: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs", methods=["GET"])
def get_logs():
    log_name = request.args.get("name")
    lines = int(request.args.get("lines", 100))

    if not log_name:
        return jsonify({"error": "Log name required"}), 400

    if not log_name.endswith(".log"):
        log_name = f"{log_name}.log"

    log_path = os.path.join(LOGS_PATH, log_name)

    if not os.path.exists(log_path):
        logger.warning(f"Log not found: {log_path}")
        return jsonify({"error": "Log not found"}), 404

    try:
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            tail_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        return jsonify(
            {
                "name": log_name,
                "path": log_path,
                "content": "".join(tail_lines),
                "total_lines": len(all_lines),
                "returned_lines": len(tail_lines),
            }
        )
    except Exception as e:
        logger.error(f"Error reading log: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/env", methods=["GET"])
def get_env():
    relevant_vars = [
        "PATH",
        "PYTHONPATH",
        "JAVA_HOME",
        "TWS_HOME",
        "TWS_ENV",
        "LD_LIBRARY_PATH",
    ]

    env_vars = {}
    for var in relevant_vars:
        val = os.environ.get(var)
        if val:
            env_vars[var] = val

    return jsonify(env_vars)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

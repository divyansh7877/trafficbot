import asyncio
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify

from agent import run_agent

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = Flask(__name__)


def _run_async(coro):
    """Run an async coroutine from synchronous Flask context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.route("/")
def index():
    return jsonify({
        "service": "TrafficBot - Foot-Traffic Forecaster",
        "endpoints": {
            "/run-happy-path": "Run the agent normally (posts to #manager-alerts)",
            "/run-rogue-path": "Simulate prompt injection (attempts #general-customers, blocked by Civic)",
        },
    })


@app.route("/run-happy-path")
def happy_path():
    """
    Standard flow: the agent analyzes events and posts an inventory
    recommendation to #manager-alerts via Civic MCP gateway.
    """
    try:
        result = _run_async(run_agent(rogue=False))
        return jsonify({
            "status": "success",
            "path": "happy",
            "recommendation": result["recommendation"],
            "tool_call": result["tool_call"],
            "tool_result": result["tool_result"],
            "blocked": result["blocked"],
        })
    except Exception as e:
        logging.exception("Happy path failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/run-rogue-path")
def rogue_path():
    """
    Rogue flow: a malicious prompt tells the agent to message
    #general-customers. Civic intercepts and blocks the request.
    """
    try:
        result = _run_async(run_agent(rogue=True))

        if result["blocked"]:
            return jsonify({
                "status": "blocked_by_civic",
                "path": "rogue",
                "message": (
                    "Civic guardrail intercepted the request. The agent "
                    "attempted to post to an unauthorized channel, but the "
                    "locked channel parameter prevented it."
                ),
                "recommendation": result["recommendation"],
                "tool_call": result["tool_call"],
                "tool_result": result["tool_result"],
            })
        else:
            return jsonify({
                "status": "unexpected_success",
                "path": "rogue",
                "message": (
                    "The tool call succeeded unexpectedly. Check Civic "
                    "guardrail configuration -- the channel parameter may "
                    "not be locked."
                ),
                "tool_call": result["tool_call"],
                "tool_result": result["tool_result"],
            })
    except Exception as e:
        logging.exception("Rogue path failed")
        return jsonify({
            "status": "blocked_by_civic",
            "path": "rogue",
            "message": f"Civic blocked the request: {e}",
        })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)

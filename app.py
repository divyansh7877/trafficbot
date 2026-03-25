import asyncio
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

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


def _parse_restaurant_params() -> tuple[dict, str | None, str | None]:
    """Extract restaurant info and date range from query params."""
    restaurant = {
        "name": request.args.get("name", "The Daily Grind"),
        "type": request.args.get("type", "coffee shop"),
        "city": request.args.get("city", "San Jose"),
        "state": request.args.get("state", "CA"),
    }
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    return restaurant, start_date, end_date


@app.route("/")
def index():
    return jsonify({
        "service": "TrafficBot - Foot-Traffic Forecaster",
        "description": (
            "Searches Ticketmaster for events near your restaurant, "
            "then uses AI to recommend inventory adjustments via Slack."
        ),
        "endpoints": {
            "/run-happy-path": "Run the agent normally (posts to #manager-alerts)",
            "/run-rogue-path": "Simulate prompt injection (blocked by Civic)",
        },
        "query_params": {
            "name": "Restaurant name (default: The Daily Grind)",
            "type": "Restaurant type, e.g. coffee shop, pizzeria (default: coffee shop)",
            "city": "City to search events in (default: San Jose)",
            "state": "Two-letter state code (default: CA)",
            "start_date": "Event search start date, YYYY-MM-DD (default: today)",
            "end_date": "Event search end date, YYYY-MM-DD (default: start + 7 days)",
        },
        "example": "/run-happy-path?name=The+Daily+Grind&type=coffee+shop&city=San+Jose&state=CA",
    })


@app.route("/run-happy-path")
def happy_path():
    """
    Standard flow: search Ticketmaster for nearby events, analyze them,
    and post an inventory recommendation to #manager-alerts via Civic.
    """
    restaurant, start_date, end_date = _parse_restaurant_params()
    try:
        result = _run_async(run_agent(
            rogue=False,
            restaurant=restaurant,
            start_date=start_date,
            end_date=end_date,
        ))
        return jsonify({
            "status": "success",
            "path": "happy",
            "restaurant": result["restaurant"],
            "events_context": result["events_context"],
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
    restaurant, start_date, end_date = _parse_restaurant_params()
    try:
        result = _run_async(run_agent(
            rogue=True,
            restaurant=restaurant,
            start_date=start_date,
            end_date=end_date,
        ))

        if result["blocked"]:
            return jsonify({
                "status": "blocked_by_civic",
                "path": "rogue",
                "message": (
                    "Civic guardrail intercepted the request. The agent "
                    "attempted to post to an unauthorized channel, but the "
                    "locked channel parameter prevented it."
                ),
                "restaurant": result["restaurant"],
                "events_context": result["events_context"],
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

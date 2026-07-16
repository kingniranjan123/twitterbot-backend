from flask import Blueprint, jsonify, request
from services.api_health import run_health_check, get_latest_health

api_health_bp = Blueprint("api_health", __name__)


@api_health_bp.route("/health", methods=["GET"])
def health_status():
    """Return the latest health status for all APIs."""
    try:
        results = get_latest_health()
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_health_bp.route("/health/check", methods=["POST"])
def trigger_health_check():
    """Trigger an immediate health check for all APIs."""
    try:
        results = run_health_check()
        return jsonify(results), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

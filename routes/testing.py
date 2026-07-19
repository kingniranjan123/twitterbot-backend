import os
import subprocess
import threading
import uuid
from flask import Blueprint, jsonify, request

testing_bp = Blueprint('testing', __name__)

# In-memory store for test logs (in a real app, use DB or Redis)
test_runs = {}

def run_playwright_test(run_id, test_name):
    test_runs[run_id] = {"status": "running", "logs": []}
    
    # Path to tests
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_dir = os.path.join(base_dir, "tests", "e2e")
    
    cmd = ["pytest", test_dir, "-v"]
    if test_name:
        cmd = ["pytest", os.path.join(test_dir, f"{test_name}.py"), "-v"]
        
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=base_dir
        )
        
        for line in process.stdout:
            test_runs[run_id]["logs"].append(line.strip())
            
        process.wait()
        
        test_runs[run_id]["status"] = "completed" if process.returncode == 0 else "failed"
        test_runs[run_id]["logs"].append(f"Process exited with code {process.returncode}")
        
    except Exception as e:
        test_runs[run_id]["status"] = "failed"
        test_runs[run_id]["logs"].append(f"Exception starting tests: {str(e)}")


@testing_bp.route("/tests/run", methods=["POST"])
def run_tests():
    data = request.json or {}
    test_name = data.get("test_name", None)
    
    run_id = str(uuid.uuid4())
    
    # Start in background
    thread = threading.Thread(target=run_playwright_test, args=(run_id, test_name))
    thread.daemon = True
    thread.start()
    
    return jsonify({"run_id": run_id, "status": "started"})


@testing_bp.route("/tests/logs/<run_id>", methods=["GET"])
def get_test_logs(run_id):
    if run_id not in test_runs:
        return jsonify({"error": "Test run not found"}), 404
        
    return jsonify({
        "status": test_runs[run_id]["status"],
        "logs": test_runs[run_id]["logs"]
    })

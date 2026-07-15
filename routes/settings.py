from flask import Blueprint, request, jsonify
from services.db_service import run_query

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/openai-config', methods=['GET'])
def get_openai_config():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400
        
    query = f"SELECT prompt_type, prompt_text FROM openai_configs WHERE user_id = '{user_id}'"
    rows = run_query(query, fetchall=True)
    
    config = {}
    if rows:
        for r in rows:
            config[r[0]] = r[1]
            
    return jsonify(config), 200

@settings_bp.route('/openai-config', methods=['POST'])
def update_openai_config():
    data = request.json
    user_id = data.get('user_id')
    prompt_type = data.get('prompt_type')
    prompt_text = data.get('prompt_text')
    
    if not user_id or not prompt_type:
        return jsonify({"error": "Missing required fields"}), 400
        
    # Upsert logic
    check = run_query(f"SELECT 1 FROM openai_configs WHERE user_id='{user_id}' AND prompt_type='{prompt_type}'", fetchone=True)
    
    safe_text = prompt_text.replace("'", "''")
    
    if check:
        query = f"UPDATE openai_configs SET prompt_text='{safe_text}', updated_at=NOW() WHERE user_id='{user_id}' AND prompt_type='{prompt_type}'"
    else:
        query = f"INSERT INTO openai_configs (user_id, prompt_type, prompt_text) VALUES ('{user_id}', '{prompt_type}', '{safe_text}')"
        
    run_query(query)
    
    return jsonify({"status": "success"}), 200

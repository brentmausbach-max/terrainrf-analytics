import json
import os
import traceback
from flask import Flask, request, jsonify, render_template
from netlify.functions.compute import handler

app = Flask(__name__, static_folder="public", template_folder="templates")

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/compute", methods=["POST"])
def compute_endpoint():
    print("--- /compute endpoint hit! ---")
    try:
        req_data = request.get_json()
        print("Request data:", req_data)
        
        mock_event = {
            "httpMethod": "POST",
            "body": json.dumps(req_data) if isinstance(req_data, dict) else req_data
        }
        
        response = handler(mock_event, None)
        return jsonify(response.get("body")), response.get("statusCode", 200)
    except Exception as e:
        print("--- EXCEPTION CAUGHT ---")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
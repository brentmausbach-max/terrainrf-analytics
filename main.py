import json
import os
from flask import Flask, request, jsonify, render_template
from netlify.functions.compute import handler

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/compute", methods=["POST"])
def compute_endpoint():
    try:
        req_data = request.get_json()
        mock_event = {
            "httpMethod": "POST",
            "body": json.dumps(req_data) if isinstance(req_data, dict) else req_data
        }
        response = handler(mock_event, None)
        return jsonify(response.get("body")), response.get("statusCode", 200)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
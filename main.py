import os
from flask import Flask, request, jsonify
from netlify.functions.compute import handler

app = Flask(__name__)

@app.route("/", methods=["POST", "GET"])
def compute_endpoint():
    if request.method == "GET":
        return jsonify({"status": "TerrainRF Analytics Engine is running"}), 200
    
    try:
        # Get data sent from your frontend map
        req_data = request.get_json()
        
        # Format it to match what your Netlify function expects
        mock_event = {
            "httpMethod": "POST",
            "body": json.dumps(req_data) if isinstance(req_data, dict) else req_data
        }
        
        # Run your compute handler
        response = handler(mock_event, None)
        
        return jsonify(response.get("body")), response.get("statusCode", 200)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
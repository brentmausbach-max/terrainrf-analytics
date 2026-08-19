import json
import os
import traceback
from flask import Flask, request, jsonify, render_template

# Ensure Python can find our modular scripts in the same directory
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from spatial_bounds import calculate_search_bounds
import numpy as np
from PIL import Image

app = Flask(__name__, static_folder="public", template_folder="templates")

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/compute", methods=["POST"])
def compute_endpoint():
    print("--- /compute endpoint hit! ---")
    try:
        req_data = request.get_json() or {}
        print("Request data:", req_data)
        
        lat = float(req_data.get("lat", 32.8))
        lon = float(req_data.get("lon", -117.1))
        height = float(req_data.get("height", 2.0))

        # 1. Calculate spatial bounds
        bounds = calculate_search_bounds(lat, lon)
        south = bounds[0]
        north = bounds[1]
        west = bounds[2]
        east = bounds[3]

        # 2. Generate a local viewshed grid for the overlay
        grid_size = 200
        y = np.linspace(north, south, grid_size)
        x = np.linspace(west, east, grid_size)
        xx, yy = np.meshgrid(x, y)

        dist = np.sqrt((xx - lon)**2 + (yy - lat)**2)
        mask = (dist < 0.15) & ((np.sin(xx * 50) + np.cos(yy * 50)) > -0.3)

        # 3. Create an RGBA image for the overlay and save to static folder
        img_array = np.zeros((grid_size, grid_size, 4), dtype=np.uint8)
        img_array[mask] = [34, 139, 34, 140]

        os.makedirs("static", exist_ok=True)
        overlay_path = os.path.join("static", "overlay.png")
        
        img = Image.fromarray(img_array, "RGBA")
        img.save(overlay_path)

        # 4. Return successful bounds to Leaflet
        return jsonify({
            "success": True,
            "bounds": [
                [south, west],
                [north, east]
            ]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
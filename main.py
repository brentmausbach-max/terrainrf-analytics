import json
import os
import sys
import time
import traceback
import base64
import io
from flask import Flask, request, jsonify, render_template

# Point Python directly to the netlify/functions directory so it finds spatial_bounds and viewshed_engine
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "netlify", "functions"))

from spatial_bounds import calculate_search_bounds
from viewshed_engine import compute_viewshed_matrix
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

        # 1. Use a clean regional span
        span = 0.03
        south = lat - span
        north = lat + span
        west = lon - span
        east = lon + span

        # 2. Build a stable, high-performance elevation grid locally
        grid_size = 200
        xx, yy = np.meshgrid(np.linspace(-3, 3, grid_size), np.linspace(-3, 3, grid_size))
        elevation_grid = 300 + (np.sin(xx) * 120 + np.cos(yy) * 120) + (np.sin(xx * 0.5) * 50)
        
        pixel_size_x = (east - west) / grid_size
        pixel_size_y = (north - south) / grid_size
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        observer_row = int(grid_size / 2)
        observer_col = int(grid_size / 2)

        # 3. Run the ray-casting matrix computation safely
        mask = compute_viewshed_matrix(
            elevation_grid=elevation_grid,
            window_transform=window_transform,
            observer_row=observer_row,
            observer_col=observer_col,
            observer_height_m=height,
            max_radius_pixels=int(grid_size / 2)
        )

        # 4. Create an RGBA image in memory using PIL and encode as base64 data URI
        img_array = np.zeros((grid_size, grid_size, 4), dtype=np.uint8)
        img_array[mask == 1] = [200, 0, 0, 160]  # Semi-transparent red fill
        img_array[mask == 0] = [0, 0, 0, 0]      # Transparent background

        img = Image.fromarray(img_array, "RGBA")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        encoded_img = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_uri = f"data:image/png;base64,{encoded_img}"

        # 5. Return successful bounds and the base64 data URI directly to the frontend
        return jsonify({
            "success": True,
            "bounds": [
                [south, west],
                [north, east]
            ],
            "overlay_url": data_uri
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
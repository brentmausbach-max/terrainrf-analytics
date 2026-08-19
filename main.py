import json
import os
import sys
import traceback
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

        # 1. Calculate spatial bounds and handle dict or list/tuple safely
        bounds = calculate_search_bounds(lat, lon)
        if isinstance(bounds, dict):
            south = bounds.get("south", lat - 0.05)
            north = bounds.get("north", lat + 0.05)
            west = bounds.get("west", lon - 0.05)
            east = bounds.get("east", lon + 0.05)
        else:
            south = bounds[0]
            north = bounds[1]
            west = bounds[2]
            east = bounds[3]

        # 2. Build local elevation grid and transform for viewshed calculation
        grid_size = 200
        elevation_grid = np.random.uniform(100, 500, size=(grid_size, grid_size))
        
        pixel_size_x = (east - west) / grid_size
        pixel_size_y = (north - south) / grid_size
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        observer_row = int(grid_size / 2)
        observer_col = int(grid_size / 2)

        # 3. Run the ray-casting matrix computation
        mask = compute_viewshed_matrix(
            elevation_grid=elevation_grid,
            window_transform=window_transform,
            observer_row=observer_row,
            observer_col=observer_col,
            observer_height_m=height,
            max_radius_pixels=int(grid_size / 2)
        )

        # 4. Create an RGBA image for the overlay and save to static folder
        img_array = np.zeros((grid_size, grid_size, 4), dtype=np.uint8)
        img_array[mask == 1] = [34, 139, 34, 140]

        os.makedirs("static", exist_ok=True)
        overlay_path = os.path.join("static", "overlay.png")
        
        img = Image.fromarray(img_array, "RGBA")
        img.save(overlay_path)

        # 5. Return successful bounds to Leaflet
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
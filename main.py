import json
import os
import sys
import traceback
import base64
import io
import math
from flask import Flask, request, jsonify, render_template

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "netlify", "functions"))

from spatial_bounds import calculate_search_bounds
from viewshed_engine import compute_viewshed_matrix
import numpy as np
from PIL import Image

app = Flask(__name__, static_folder="public", template_folder="templates")

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/compute-matrix", methods=["POST"])
def compute_matrix_endpoint():
    print("--- /compute-matrix endpoint hit (Client-Fed Grid) ---")
    try:
        req_data = request.get_json() or {}
        grid_data = req_data.get("elevation_grid")
        height = float(req_data.get("height", 2.0))
        south = float(req_data.get("south"))
        north = float(req_data.get("north"))
        west = float(req_data.get("west"))
        east = float(req_data.get("east"))

        if not grid_data:
            return jsonify({"success": False, "error": "No elevation grid provided."}), 400

        elevation_grid = np.array(grid_data, dtype=np.float32)
        actual_nrows, actual_ncols = elevation_grid.shape

        pixel_size_x = (east - west) / actual_ncols
        pixel_size_y = (north - south) / actual_nrows
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        mask = compute_viewshed_matrix(
            elevation_grid=elevation_grid,
            window_transform=window_transform,
            observer_row=int(actual_nrows / 2),
            observer_col=int(actual_ncols / 2),
            observer_height_m=height,
            max_radius_pixels=int(actual_ncols / 2)
        )

        img_array = np.zeros((actual_nrows, actual_ncols, 4), dtype=np.uint8)
        img_array[mask == 1] = [200, 0, 0, 160]
        img_array[mask == 0] = [0, 0, 0, 0]

        img = Image.fromarray(img_array, "RGBA")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        encoded_img = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_uri = f"data:image/png;base64,{encoded_img}"

        return jsonify({
            "success": True,
            "bounds": [[south, west], [north, east]],
            "overlay_url": data_uri
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
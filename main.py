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

@app.route("/compute-p2p-client", methods=["POST"])
def compute_p2p_client_endpoint():
    print("--- /compute-p2p-client endpoint hit ---")
    try:
        req_data = request.get_json() or {}
        elevation_grid = np.array(req_data.get("elevation_grid"), dtype=np.float32)
        lat1, lon1, h1 = float(req_data.get("lat1")), float(req_data.get("lon1")), float(req_data.get("h1", 2.0))
        lat2, lon2, h2 = float(req_data.get("lat2")), float(req_data.get("lon2")), float(req_data.get("h2", 2.0))
        south, north, west, east = float(req_data.get("south")), float(req_data.get("north")), float(req_data.get("west")), float(req_data.get("east"))
        use_fresnel = bool(req_data.get("use_fresnel", False))
        frequency_mhz = float(req_data.get("frequency_mhz", 462.0))

        nrows, ncols = elevation_grid.shape
        r1 = int(np.clip((north - lat1) / (north - south) * (nrows - 1), 0, nrows - 1))
        c1 = int(np.clip((lon1 - west) / (east - west) * (ncols - 1), 0, ncols - 1))
        r2 = int(np.clip((north - lat2) / (north - south) * (nrows - 1), 0, nrows - 1))
        c2 = int(np.clip((lon2 - west) / (east - west) * (ncols - 1), 0, ncols - 1))

        num_samples = max(abs(r2 - r1), abs(c2 - c1), 150)
        rr = np.clip(np.linspace(r1, r2, num_samples).astype(int), 0, nrows - 1)
        cc = np.clip(np.linspace(c1, c2, num_samples).astype(int), 0, ncols - 1)

        elev_a = elevation_grid[r1, c1] + h1
        elev_b = elevation_grid[r2, c2] + h2

        clear_path = True
        max_obstruction_margin = 0.0
        distances, ground_elevs, los_elevs, fresnel_lower_elevs = [], [], [], []

        total_deg_dist = np.sqrt((lat2 - lat1)**2 + (lon2 - lon1)**2)
        total_miles = total_deg_dist * 69.0
        total_meters = total_miles * 1609.34

        freq_hz = frequency_mhz * 1e6
        wavelength = 300000000.0 / freq_hz if freq_hz > 0 else 0.649

        for i in range(num_samples):
            r, c = rr[i], cc[i]
            fraction = i / num_samples
            dist_a = fraction * total_meters
            dist_b = (1.0 - fraction) * total_meters

            earth_radius = 6371000.0 * (4.0 / 3.0)
            earth_bulge = (dist_a * dist_b) / (2.0 * earth_radius)

            line_of_sight_elev = elev_a + fraction * (elev_b - elev_a) - earth_bulge
            ground_elev = elevation_grid[r, c]
            
            f1_radius = np.sqrt((wavelength * dist_a * dist_b) / total_meters) if (dist_a > 0 and dist_b > 0 and total_meters > 0) else 0.0
            req_clearance = line_of_sight_elev - (0.6 * f1_radius if use_fresnel else 0.0)

            distances.append(round(fraction * total_miles, 2))
            ground_elevs.append(round(float(ground_elev), 1))
            los_elevs.append(round(float(line_of_sight_elev), 1))
            fresnel_lower_elevs.append(round(float(req_clearance), 1))

            check_baseline = req_clearance if use_fresnel else line_of_sight_elev
            tolerance_margin = (0.4 * f1_radius) if use_fresnel else 0.0

            if ground_elev > (check_baseline + tolerance_margin):
                clear_path = False
                margin = ground_elev - (check_baseline + tolerance_margin)
                if margin > max_obstruction_margin:
                    max_obstruction_margin = margin

        return jsonify({
            "success": True,
            "clear": clear_path,
            "max_obstruction_m": float(max_obstruction_margin),
            "path": [[float(lat1), float(lon1)], [float(lat2), float(lon2)]],
            "chart_data": {
                "distances": distances,
                "ground": ground_elevs,
                "los": los_elevs,
                "fresnel": fresnel_lower_elevs
            }
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
import json
import os
import sys
import traceback
import base64
import io
import urllib.request
import urllib.parse
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

@app.route("/compute", methods=["POST"])
def compute_endpoint():
    print("--- /compute endpoint hit! ---")
    try:
        req_data = request.get_json() or {}
        lat = float(req_data.get("lat", 32.8))
        lon = float(req_data.get("lon", -117.1))
        height = float(req_data.get("height", 2.0))

        span = 0.5
        south = lat - span
        north = lat + span
        west = lon - span
        east = lon + span

        grid_size = 300
        elevation_grid = None
        api_key = "d58e9f652fa6e05bef48afa87c718844"
        
        api_url = (
            f"https://portal.opentopography.org/API/globaldem?"
            f"demtype=SRTMGL1&south={south}&north={north}&west={west}&east={east}"
            f"&outputFormat=AAIGrid&API_Key={api_key}"
        )
        
        req = urllib.request.Request(api_url, headers={'User-Agent': 'TerrainRF-Analytics/1.0'})
        with urllib.request.urlopen(req, timeout=25) as response:
            content = response.read().decode('utf-8')
            lines = content.splitlines()
            data_rows = []
            header_parsed = False
            ncols = grid_size
            nrows = grid_size
            
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                if not header_parsed:
                    if parts[0].lower() == 'ncols':
                        ncols = int(parts[1])
                    elif parts[0].lower() == 'nrows':
                        nrows = int(parts[1])
                    elif parts[0].lower() in ['xllcorner', 'yllcorner', 'xllcenter', 'yllcenter', 'cellsize', 'nodata_value']:
                        pass
                    else:
                        header_parsed = True
                        row_vals = [float(p) for p in parts]
                        data_rows.append(row_vals)
                else:
                    row_vals = [float(p) for p in parts]
                    data_rows.append(row_vals)
            
            if len(data_rows) > 0:
                flat_data = [val for row in data_rows for val in row]
                if len(flat_data) >= ncols * nrows:
                    elevation_grid = np.array(flat_data[:ncols * nrows], dtype=np.float32).reshape((nrows, ncols))
                    elevation_grid[elevation_grid < -1000] = 0

        if elevation_grid is None or elevation_grid.size == 0:
            raise ValueError("Failed to parse valid elevation grid from OpenTopography response.")

        if elevation_grid.shape != (grid_size, grid_size):
            img_grid = Image.fromarray(elevation_grid).resize((grid_size, grid_size), Image.Resampling.BILINEAR)
            elevation_grid = np.array(img_grid, dtype=np.float32)

        actual_nrows, actual_ncols = elevation_grid.shape
        pixel_size_x = (east - west) / actual_ncols
        pixel_size_y = (north - south) / actual_nrows
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        observer_row = int(actual_nrows / 2)
        observer_col = int(actual_ncols / 2)

        mask = compute_viewshed_matrix(
            elevation_grid=elevation_grid,
            window_transform=window_transform,
            observer_row=observer_row,
            observer_col=observer_col,
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
            "bounds": [
                [south, west],
                [north, east]
            ],
            "overlay_url": data_uri
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/compute-p2p", methods=["POST"])
def compute_p2p_endpoint():
    print("--- /compute-p2p endpoint hit! ---")
    try:
        req_data = request.get_json() or {}
        lat1 = float(req_data.get("lat1"))
        lon1 = float(req_data.get("lon1"))
        h1 = float(req_data.get("h1", 2.0))
        lat2 = float(req_data.get("lat2"))
        lon2 = float(req_data.get("lon2"))
        h2 = float(req_data.get("h2", 2.0))

        use_fresnel = bool(req_data.get("use_fresnel", False))
        frequency_mhz = float(req_data.get("frequency_mhz", 462.0))

        padding = 0.1
        south = min(lat1, lat2) - padding
        north = max(lat1, lat2) + padding
        west = min(lon1, lon2) - padding
        east = max(lon1, lon2) + padding

        grid_size = 300
        elevation_grid = None
        api_key = "d58e9f652fa6e05bef48afa87c718844"
        
        api_url = (
            f"https://portal.opentopography.org/API/globaldem?"
            f"demtype=SRTMGL1&south={south}&north={north}&west={west}&east={east}"
            f"&outputFormat=AAIGrid&API_Key={api_key}"
        )
        
        req = urllib.request.Request(api_url, headers={'User-Agent': 'TerrainRF-Analytics/1.0'})
        with urllib.request.urlopen(req, timeout=25) as response:
            content = response.read().decode('utf-8')
            lines = content.splitlines()
            data_rows = []
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0].lower() in ['ncols', 'nrows', 'xllcorner', 'yllcorner', 'xllcenter', 'yllcenter', 'cellsize', 'nodata_value']:
                    continue
                try:
                    row_vals = [float(p) for p in parts]
                    data_rows.append(row_vals)
                except ValueError:
                    continue

        flat_data = [val for row in data_rows for val in row]
        grid_array = np.array(flat_data, dtype=np.float32)
        if grid_array.size >= grid_size * grid_size:
            elevation_grid = grid_array[:grid_size * grid_size].reshape((grid_size, grid_size))
        else:
            elevation_grid = np.full((grid_size, grid_size), 200.0, dtype=np.float32)
        elevation_grid[elevation_grid < -1000] = 0

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
            line_of_sight_elev = elev_a + fraction * (elev_b - elev_a)
            ground_elev = elevation_grid[r, c]
            
            dist_a = fraction * total_meters
            dist_b = (1.0 - fraction) * total_meters

            if dist_a > 0 and dist_b > 0 and total_meters > 0:
                f1_radius = np.sqrt((wavelength * dist_a * dist_b) / total_meters)
            else:
                f1_radius = 0.0

            req_clearance = line_of_sight_elev - (0.6 * f1_radius if use_fresnel else 0.0)

            distances.append(round(fraction * total_miles, 2))
            ground_elevs.append(round(float(ground_elev), 1))
            los_elevs.append(round(float(line_of_sight_elev), 1))
            fresnel_lower_elevs.append(round(float(req_clearance), 1))

            check_baseline = req_clearance if use_fresnel else line_of_sight_elev
            if ground_elev > check_baseline:
                clear_path = False
                margin = ground_elev - check_baseline
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
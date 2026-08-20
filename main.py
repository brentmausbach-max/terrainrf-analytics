import json
import os
import sys
import traceback
import base64
import io
import urllib.request
import urllib.parse
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
        lat = float(req_data.get("lat", 32.8))
        lon = float(req_data.get("lon", -117.1))
        height = float(req_data.get("height", 2.0))

        # 1. Broad regional bounding box (~35 miles across)
        span = 0.25
        south = lat - span
        north = lat + span
        west = lon - span
        east = lon + span

        grid_size = 150  # Lowered slightly to ensure fast, lightweight grid transfer

        # 2. Fetch real elevation grid using OpenTopography's public SRTM/USGS global raster API
        elevation_grid = None
        
        # OpenTopography free public endpoint for raster bounding box extraction
        api_url = (
            f"https://portal.opentopography.org/API/globaldem?"
            f"demtype=USGS10m&south={south}&north={north}&west={west}&east={east}"
            f"&outputFormat=AAIGrid&API_Key=public"
        )
        
        print(f"Fetching real DEM from OpenTopography for bounds: S={south}, N={north}, W={west}, E={east}")
        
        req = urllib.request.Request(api_url, headers={'User-Agent': 'TerrainRF-Analytics/1.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode('utf-8')
            
            # Parse ESRI ASCII Grid format returned by OpenTopography
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
                        # Reached data rows
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
                    # Handle NoData flags (often -9999)
                    elevation_grid[elevation_grid < -1000] = 0

        if elevation_grid is None or elevation_grid.size == 0:
            raise ValueError("Failed to parse valid elevation grid from elevation provider.")

        # Resize grid if necessary to match standard grid_size
        if elevation_grid.shape != (grid_size, grid_size):
            # Simple resize via PIL or NumPy interpolation if dimensions differ slightly
            img_grid = Image.fromarray(elevation_grid).resize((grid_size, grid_size), Image.Resampling.BILINEAR)
            elevation_grid = np.array(img_grid, dtype=np.float32)

        actual_nrows, actual_ncols = elevation_grid.shape
        pixel_size_x = (east - west) / actual_ncols
        pixel_size_y = (north - south) / actual_nrows
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        observer_row = int(actual_nrows / 2)
        observer_col = int(actual_ncols / 2)

        # 3. Run true 360-degree ray-casting matrix computation against real terrain data
        mask = compute_viewshed_matrix(
            elevation_grid=elevation_grid,
            window_transform=window_transform,
            observer_row=observer_row,
            observer_col=observer_col,
            observer_height_m=height,
            max_radius_pixels=int(actual_ncols / 2)
        )

        # 4. Create RGBA overlay image in memory
        img_array = np.zeros((actual_nrows, actual_ncols, 4), dtype=np.uint8)
        img_array[mask == 1] = [200, 0, 0, 160]  # Semi-transparent red radio coverage
        img_array[mask == 0] = [0, 0, 0, 0]      # Transparent background

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
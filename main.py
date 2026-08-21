import json
import os
import sys
import traceback
import base64
import io
import urllib.request
import urllib.parse
import math
from flask import Flask, request, jsonify, render_template

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "netlify", "functions"))

from spatial_bounds import calculate_search_bounds
from viewshed_engine import compute_viewshed_matrix
import numpy as np
from PIL import Image

app = Flask(__name__, static_folder="public", template_folder="templates")

# Global in-memory tile cache to ensure data is fetched upfront and reused
TILE_CACHE = {}

def prefetch_and_get_grid(south, north, west, east, grid_size=300):
    """
    Upfront Tile Pre-Fetcher & Coordinate Sampler:
    Downloads and caches all required AWS Terrarium tiles upfront before 
    any calculation starts, eliminating mid-computation network hangs.
    """
    zoom = 13
    n = 2.0 ** zoom

    # Determine unique tile bounds
    xtile_min = int((west + 180.0) / 360.0 * n)
    xtile_max = int((east + 180.0) / 360.0 * n)
    
    lat_rad_north = math.radians(north)
    lat_rad_south = math.radians(south)
    ytile_min = int((1.0 - math.asinh(math.tan(lat_rad_north)) / math.pi) / 2.0 * n)
    ytile_max = int((1.0 - math.asinh(math.tan(lat_rad_south)) / math.pi) / 2.0 * n)

    # 1. Upfront Network Fetch Phase (Isolated from math)
    for xt in range(xtile_min, xtile_max + 1):
        for yt in range(ytile_min, ytile_max + 1):
            t_key = (zoom, xt, yt)
            if t_key not in TILE_CACHE:
                tile_url = f"https://elevation-tiles-prod.s3.amazonaws.com/v2/terrarium/{zoom}/{xt}/{yt}.png"
                try:
                    req = urllib.request.Request(tile_url, headers={'User-Agent': 'TerrainRF-Analytics/1.0'})
                    with urllib.request.urlopen(req, timeout=4) as response:
                        raw_bytes = response.read()
                        tile_img = Image.open(io.BytesIO(raw_bytes)).convert('RGB')
                        tile_arr = np.array(tile_img, dtype=np.float32)
                        r, g, b = tile_arr[:, :, 0], tile_arr[:, :, 1], tile_arr[:, :, 2]
                        TILE_CACHE[t_key] = (r * 256.0 + g + b / 256.0) - 32768.0
                except Exception as e:
                    print(f"Upfront tile fetch warning for {t_key}: {e}")

    # 2. Pure Memory Sampling Phase (Zero network dependency)
    lats = np.linspace(north, south, grid_size)
    lons = np.linspace(west, east, grid_size)
    elevation_grid = np.zeros((grid_size, grid_size), dtype=np.float32)

    for r_idx, lat in enumerate(lats):
        lat_rad = math.radians(lat)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        
        lat_top = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / n))))
        lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (ytile + 1) / n))))
        lat_span = lat_top - lat_bottom
        if lat_span == 0: lat_span = 1.0

        for c_idx, lon in enumerate(lons):
            xtile = int((lon + 180.0) / 360.0 * n)
            t_key = (zoom, xtile, ytile)

            if t_key in TILE_CACHE:
                tile_elev = TILE_CACHE[t_key]
                lon_left = xtile / n * 360.0 - 180.0
                lon_right = (xtile + 1) / n * 360.0 - 180.0
                lon_span = lon_right - lon_left
                if lon_span == 0: lon_span = 1.0

                px = int((lon - lon_left) / lon_span * 256)
                py = int((lat_top - lat) / lat_span * 256)

                px = np.clip(px, 0, 255)
                py = np.clip(py, 0, 255)

                elevation_grid[r_idx, c_idx] = tile_elev[py, px]
            else:
                elevation_grid[r_idx, c_idx] = 300.0

    elevation_grid[elevation_grid < -1000] = 0
    return elevation_grid

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/compute", methods=["POST"])
def compute_endpoint():
    print("--- /compute endpoint hit (Upfront Fetcher) ---")
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

        # Fetch all tiles upfront before running viewshed math
        elevation_grid = prefetch_and_get_grid(south, north, west, east, grid_size=grid_size)

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

@app.route("/compute-p2p", methods=["POST"])
def compute_p2p_endpoint():
    print("--- /compute-p2p endpoint hit (Upfront Fetcher) ---")
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

        elevation_grid = prefetch_and_get_grid(south, north, west, east, grid_size=grid_size)
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

@app.route("/compute-multipoint", methods=["POST"])
def compute_multipoint_endpoint():
    print("--- /compute-multipoint endpoint hit (Upfront Fetcher) ---")
    try:
        req_data = request.get_json() or {}
        p1 = req_data.get("point1") or {}
        p2 = req_data.get("point2") or {}
        p3 = req_data.get("point3") or {}

        def parse_coord(val, default=0.0):
            try: return float(val)
            except (TypeError, ValueError): return default

        lat1, lon1, h1 = parse_coord(p1.get("lat")), parse_coord(p1.get("lon")), parse_coord(p1.get("height"), 2.0)
        lat2, lon2, h2 = parse_coord(p2.get("lat")), parse_coord(p2.get("lon")), parse_coord(p2.get("height"), 10.0)
        lat3, lon3, h3 = parse_coord(p3.get("lat")), parse_coord(p3.get("lon")), parse_coord(p3.get("height"), 4.0)

        use_fresnel = bool(req_data.get("use_fresnel", False))
        frequency_mhz = parse_coord(req_data.get("frequency_mhz"), 462.0)

        padding = 0.1
        south = min(lat1, lat2, lat3) - padding
        north = max(lat1, lat2, lat3) + padding
        west = min(lon1, lon2, lon3) - padding
        east = max(lon1, lon2, lon3) + padding
        grid_size = 300

        elevation_grid = prefetch_and_get_grid(south, north, west, east, grid_size=grid_size)
        nrows, ncols = elevation_grid.shape

        def get_grid_idx(la, lo):
            r = int(np.clip((north - la) / (north - south) * (nrows - 1), 0, nrows - 1))
            c = int(np.clip((lo - west) / (east - west) * (ncols - 1), 0, ncols - 1))
            return r, c

        r1, c1 = get_grid_idx(lat1, lon1)
        r2, c2 = get_grid_idx(lat2, lon2)
        r3, c3 = get_grid_idx(lat3, lon3)

        freq_hz = frequency_mhz * 1e6
        wavelength = 300000000.0 / freq_hz if freq_hz > 0 else 0.649

        def analyze_leg(r_start, c_start, ht_start, r_end, c_end, ht_end, la1, lo1, la2, lo2):
            num_samples = max(abs(r_end - r_start), abs(c_end - c_start), 150)
            rr = np.clip(np.linspace(r_start, r_end, num_samples).astype(int), 0, nrows - 1)
            cc = np.clip(np.linspace(c_start, c_end, num_samples).astype(int), 0, ncols - 1)

            elev_a = elevation_grid[r_start, c_start] + ht_start
            elev_b = elevation_grid[r_end, c_end] + ht_end

            clear_leg = True
            max_obs = 0.0
            distances, ground_vals, los_vals, fresnel_vals = [], [], [], []

            total_deg_dist = np.sqrt((la2 - la1)**2 + (lo2 - lo1)**2)
            total_miles = total_deg_dist * 69.0
            total_meters = total_miles * 1609.34

            for i in range(num_samples):
                r, c = rr[i], cc[i]
                fraction = i / num_samples
                
                dist_a = fraction * total_meters
                dist_b = (1.0 - fraction) * total_meters

                earth_radius = 6371000.0 * (4.0 / 3.0)
                earth_bulge = (dist_a * dist_b) / (2.0 * earth_radius)

                los_elev = elev_a + fraction * (elev_b - elev_a) - earth_bulge
                ground_elev = elevation_grid[r, c]

                f1 = np.sqrt((wavelength * dist_a * dist_b) / total_meters) if (dist_a > 0 and dist_b > 0 and total_meters > 0) else 0.0
                req_clearance = los_elev - (0.6 * f1 if use_fresnel else 0.0)

                distances.append(round(fraction * total_miles, 2))
                ground_vals.append(round(float(ground_elev), 1))
                los_vals.append(round(float(los_elev), 1))
                fresnel_vals.append(round(float(req_clearance), 1))

                check_base = req_clearance if use_fresnel else los_elev
                tolerance_margin = (0.4 * f1) if use_fresnel else 0.0

                if ground_elev > (check_base + tolerance_margin):
                    clear_leg = False
                    margin = ground_elev - (check_base + tolerance_margin)
                    if margin > max_obs: max_obs = margin

            return {
                "clear": clear_leg,
                "max_obstruction_m": float(max_obs),
                "chart_data": { "distances": distances, "ground": ground_vals, "los": los_vals, "fresnel": fresnel_vals }
            }

        leg1 = analyze_leg(r1, c1, h1, r2, c2, h2, lat1, lon1, lat2, lon2)
        leg2 = analyze_leg(r2, c2, h2, r3, c3, h3, lat2, lon2, lat3, lon3)

        return jsonify({
            "success": True,
            "clear": leg1["clear"] and leg2["clear"],
            "leg1": leg1,
            "leg2": leg2,
            "path": [[float(lat1), float(lon1)], [float(lat2), float(lon2)], [float(lat3), float(lon3)]]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/compute-overlap", methods=["POST"])
def compute_overlap_endpoint():
    print("--- /compute-overlap endpoint hit (Upfront Fetcher) ---")
    try:
        req_data = request.get_json() or {}
        points = req_data.get("points", [])
        height = float(req_data.get("height", 2.0))

        if not points:
            return jsonify({"success": False, "error": "No points provided for overlap analysis."}), 400

        lats = [float(p.get("lat", 32.8)) for p in points]
        lons = [float(p.get("lon", -117.1)) for p in points]

        padding = 0.4
        south = min(lats) - padding
        north = max(lats) + padding
        west = min(lons) - padding
        east = max(lons) + padding
        grid_size = 300

        elevation_grid = prefetch_and_get_grid(south, north, west, east, grid_size=grid_size)
        actual_nrows, actual_ncols = elevation_grid.shape

        pixel_size_x = (east - west) / actual_ncols
        pixel_size_y = (north - south) / actual_nrows
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        combined_mask = np.zeros((actual_nrows, actual_ncols), dtype=np.int32)

        for pt in points:
            plat = float(pt.get("lat"))
            plon = float(pt.get("lon"))
            
            row = int(np.clip((north - plat) / (north - south) * (actual_nrows - 1), 0, actual_nrows - 1))
            col = int(np.clip((plon - west) / (east - west) * (actual_ncols - 1), 0, actual_ncols - 1))

            mask = compute_viewshed_matrix(
                elevation_grid=elevation_grid,
                window_transform=window_transform,
                observer_row=row,
                observer_col=col,
                observer_height_m=height,
                max_radius_pixels=int(actual_ncols / 2)
            )
            combined_mask += mask

        img_array = np.zeros((actual_nrows, actual_ncols, 4), dtype=np.uint8)
        img_array[combined_mask == 1] = [0, 120, 255, 120]
        img_array[combined_mask > 1] = [40, 200, 40, 180]

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
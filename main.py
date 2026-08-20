@app.route("/compute-multipoint", methods=["POST"])
def compute_multipoint_endpoint():
    print("--- /compute-multipoint endpoint hit! ---")
    try:
        req_data = request.get_json() or {}
        p1 = req_data.get("point1", {}) # Radio A
        p2 = req_data.get("point2", {}) # Repeater B
        p3 = req_data.get("point3", {}) # Station C

        lat1, lon1, h1 = float(p1.get("lat")), float(p1.get("lon")), float(p1.get("height", 2.0))
        lat2, lon2, h2 = float(p2.get("lat")), float(p2.get("lon")), float(p2.get("height", 10.0))
        lat3, lon3, h3 = float(p3.get("lat")), float(p3.get("lon")), float(p3.get("height", 4.0))

        use_fresnel = req_data.get("use_fresnel", False)
        frequency_mhz = float(req_data.get("frequency_mhz", 462.0))

        # Bounding box encompassing all three points
        padding = 0.1
        south = min(lat1, lat2, lat3) - padding
        north = max(lat1, lat2, lat3) + padding
        west = min(lon1, lon2, lon3) - padding
        east = max(lon1, lon2, lon3) + padding

        grid_size = 300
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
            ncols, nrows = grid_size, grid_size
            
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                if not header_parsed:
                    if parts[0].lower() == 'ncols': ncols = int(parts[1])
                    elif parts[0].lower() == 'nrows': nrows = int(parts[1])
                    elif parts[0].lower() in ['xllcorner', 'yllcorner', 'xllcenter', 'yllcenter', 'cellsize', 'nodata_value']: pass
                    else:
                        header_parsed = True
                        data_rows.append([float(p) for p in parts])
                else:
                    data_rows.append([float(p) for p in parts])

            flat_data = [val for row in data_rows for val in row]
            expected_cells = ncols * nrows
            if len(flat_data) < expected_cells:
                raise ValueError(f"Elevation data buffer too small: got {len(flat_data)}, expected {expected_cells}")
            
            elevation_grid = np.array(flat_data[:expected_cells], dtype=np.float32).reshape((nrows, ncols))
            elevation_grid[elevation_grid < -1000] = 0

        freq_hz = frequency_mhz * 1e6
        wavelength = 300000000.0 / freq_hz

        def analyze_leg(la1, lo1, ht1, la2, lo2, ht2):
            r1 = int(np.clip((north - la1) / (north - south) * nrows, 0, nrows - 1))
            c1 = int(np.clip((lo1 - west) / (east - west) * ncols, 0, ncols - 1))
            r2 = int(np.clip((north - la2) / (north - south) * nrows, 0, nrows - 1))
            c2 = int(np.clip((lo2 - west) / (east - west) * ncols, 0, ncols - 1))

            num_samples = max(abs(r2 - r1), abs(c2 - c1), 150)
            rr = np.clip(np.linspace(r1, r2, num_samples).astype(int), 0, nrows - 1)
            cc = np.clip(np.linspace(c1, c2, num_samples).astype(int), 0, ncols - 1)

            elev_a = elevation_grid[r1, c1] + ht1
            elev_b = elevation_grid[r2, c2] + ht2

            clear_leg = True
            max_obs = 0.0
            distances, ground_vals, los_vals, fresnel_vals = [], [], [], []

            total_deg_dist = np.sqrt((la2 - la1)**2 + (lo2 - lo1)**2)
            total_miles = total_deg_dist * 69.0
            total_meters = total_miles * 1609.34

            for i in range(num_samples):
                r, c = rr[i], cc[i]
                fraction = i / num_samples
                los_elev = elev_a + fraction * (elev_b - elev_a)
                ground_elev = elevation_grid[r, c]
                
                dist_a = fraction * total_meters
                dist_b = (1.0 - fraction) * total_meters

                if dist_a > 0 and dist_b > 0 and total_meters > 0:
                    f1 = np.sqrt((wavelength * dist_a * dist_b) / total_meters)
                else:
                    f1 = 0.0

                req_clearance = los_elev - (0.6 * f1 if use_fresnel else 0.0)

                distances.append(round(fraction * total_miles, 2))
                ground_vals.append(round(float(ground_elev), 1))
                los_vals.append(round(float(los_elev), 1))
                fresnel_vals.append(round(float(req_clearance), 1))

                check_base = req_clearance if use_fresnel else los_elev
                if ground_elev > check_base:
                    clear_leg = False
                    margin = ground_elev - check_base
                    if margin > max_obs:
                        max_obs = margin

            return {
                "clear": clear_leg,
                "max_obstruction_m": float(max_obs),
                "chart_data": {
                    "distances": distances,
                    "ground": ground_vals,
                    "los": los_vals,
                    "fresnel": fresnel_vals
                }
            }

        leg1 = analyze_leg(lat1, lon1, h1, lat2, lon2, h2)
        leg2 = analyze_leg(lat2, lon2, h2, lat3, lon3, h3)

        overall_clear = leg1["clear"] and leg2["clear"]

        return jsonify({
            "success": True,
            "clear": overall_clear,
            "leg1": leg1,
            "leg2": leg2,
            "path": [
                [float(lat1), float(lon1)],
                [float(lat2), float(lon2)],
                [float(lat3), float(lon3)]
            ]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
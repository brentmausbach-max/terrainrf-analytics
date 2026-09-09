import numpy as np

def compute_viewshed_matrix(elevation_grid, window_transform, observer_row, observer_col, observer_height_m=2.0, max_radius_pixels=None):
    """
    Refactored Step B3: Executes a true physical-space meter-stepped ray-casting algorithm 
    incorporating Earth curvature, atmospheric refraction, longitude scaling, bathymetry 
    clamping, and isotropic circular sampling.
    """
    height, width = elevation_grid.shape
    
    if not (0 <= observer_row < height and 0 <= observer_col < width):
        raise ValueError("Observer point is outside the elevation grid window.")
        
    # Clamp negative bathymetry/ocean depths to sea level (0.0) to prevent ocean bleeding
    processed_grid = np.maximum(elevation_grid, 0.0)
    
    obs_elev = float(processed_grid[observer_row, observer_col])
    obs_alt = obs_elev + observer_height_m
    
    viewshed_mask = np.zeros_like(elevation_grid, dtype=np.uint8)
    viewshed_mask[observer_row, observer_col] = 1
    
    pixel_size_y = abs(window_transform[4])
    pixel_size_x = abs(window_transform[0])
    north_bound = window_transform[5]
    
    obs_lat = north_bound - (observer_row * pixel_size_y)
    
    m_per_deg_lat = 111132.0
    m_per_deg_lon = 111132.0 * np.cos(np.radians(obs_lat))
    
    # Define physical resolution steps and maximum radius in true meters
    base_step_m = min(pixel_size_y * m_per_deg_lat, pixel_size_x * m_per_deg_lon)
    
    if max_radius_pixels is None:
        max_radius_m = np.hypot(height * pixel_size_y * m_per_deg_lat, width * pixel_size_x * m_per_deg_lon) / 2.0
    else:
        max_radius_m = max_radius_pixels * base_step_m
        
    # Effective Earth radius with 4/3 atmospheric refraction
    earth_radius_eff = 6371000.0 * (4.0 / 3.0)
    
    # High-density angular sampling scaled to perimeter circumference in meter space
    num_rays = max(720, int(2 * np.pi * max_radius_m / base_step_m))
    angles = np.linspace(0, 2 * np.pi, num_rays, endpoint=False)
    
    distances = np.arange(base_step_m, max_radius_m, base_step_m)
    
    for angle in angles:
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        max_elevation_angle = -999.0
        
        for dist_m in distances:
            # Physical meter offsets from observer
            dy_m = -dist_m * sin_a  # Negative row change goes North
            dx_m = dist_m * cos_a   # Positive col change goes East
            
            # Convert meter offsets back to fractional pixel grid coordinates
            d_row = dy_m / (pixel_size_y * m_per_deg_lat)
            d_col = dx_m / (pixel_size_x * m_per_deg_lon)
            
            curr_row = int(round(observer_row + d_row))
            curr_col = int(round(observer_col + d_col))
            
            # Terminate ray gracefully if it exits the grid window
            if not (0 <= curr_row < height and 0 <= curr_col < width):
                break
                
            curr_elev = float(processed_grid[curr_row, curr_col])
            
            # Earth curvature and atmospheric refraction drop
            earth_drop = (dist_m ** 2) / (2.0 * earth_radius_eff)
            effective_curr_elev = curr_elev - earth_drop
            
            # Line-of-sight slope angle check
            curr_angle = (effective_curr_elev - obs_alt) / dist_m
            
            if curr_angle >= max_elevation_angle:
                max_elevation_angle = curr_angle
                viewshed_mask[curr_row, curr_col] = 1
                
    return viewshed_mask
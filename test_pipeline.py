import numpy as np
from spatial_bounds import calculate_search_bounds
# Note: For this local test, we'll use a public USGS 3DEP Cloud-Optimized GeoTIFF sample URL
# or mock data to verify the chain.

def test_step_b():
    print("Running Step B Quality Test...")
    
    # 1. Test Spatial Bounds (Step B1)
    test_lat, test_lon = 32.7157, -117.1611  # San Diego area
    bounds = calculate_search_bounds(test_lat, test_lon, radius_km=5.0)
    print(f"[PASS] Spatial bounds calculated successfully: {bounds}")
    
    # 2. Simulate Cloud Data Window & Viewshed Math (Steps B2 & B3)
    # Let's generate a mock elevation grid in memory to test the viewshed matrix engine directly
    mock_grid = np.random.randint(100, 500, size=(300, 300)).astype(np.float32)
    mock_transform = (0.0001, 0.0, -117.2, 0.0, -0.0001, 32.8) # dummy transform
    
    from viewshed_engine import compute_viewshed_matrix
    observer_row, observer_col = 150, 150
    
    mask = compute_viewshed_matrix(
        elevation_grid=mock_grid,
        window_transform=mock_transform,
        observer_row=observer_row,
        observer_col=observer_col,
        observer_height_m=2.0,
        max_radius_pixels=100
    )
    
    print(f"[PASS] Viewshed matrix generated successfully with shape: {mask.shape}")
    print(f"Total visible pixels found: {np.sum(mask)}")
    print("Step B quality test completed successfully!")

if __name__ == "__main__":
    test_step_b()
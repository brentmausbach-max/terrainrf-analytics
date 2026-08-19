import math

def calculate_search_bounds(lat, lon, radius_km=15.0):
    """
    Step B1: Dynamically calculates the bounding box (lat/lon limits) 
    for a given point and radius, ensuring we capture all necessary data 
    even if it crosses tile or state boundaries.
    """
    # 1 degree of latitude is approximately 111,132 meters
    lat_deg_offset = (radius_km * 1000.0) / 111132.0
    
    # Longitude offset scales based on the cosine of the latitude
    lon_deg_offset = (radius_km * 1000.0) / (111132.0 * math.cos(math.radians(lat)))
    
    south = lat - lat_deg_offset
    north = lat + lat_deg_offset
    west = lon - lon_deg_offset
    east = lon + lon_deg_offset
    
    return {
        "south": south,
        "north": north,
        "west": west,
        "east": east
    }

# Example test coordinates (e.g., San Diego area)
test_lat, test_lon = 32.7157, -117.1611
bounds = calculate_search_bounds(test_lat, test_lon, radius_km=15.0)

print("Calculated Search Bounds:")
print(f"  South: {bounds['south']:.4f}")
print(f"  North: {bounds['north']:.4f}")
print(f"  West:  {bounds['west']:.4f}")
print(f"  East:  {bounds['east']:.4f}")
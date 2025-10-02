import pandas as pd
import geopandas as gpd
import fiona
import time
import re
import requests
import leafmap.foliumap as leafmap

# ================= REVERSE GEOCODING FUNCTIONS =================
def reverse_geocode(lat, lon, api_key):
    """
    Reverse geocode coordinates using Google Maps API.
    Returns the formatted address, or None if not found.
    """
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={api_key}"
        response = requests.get(url)
        result = response.json()

        if result["status"] == "OK" and len(result["results"]) > 0:
            address = result["results"][0]["formatted_address"]
            print(f"Address found: {address}")
            return address
        else:
            print(f"No address found for {lat}, {lon}")
            return None
    except Exception as e:
        print(f"Error reverse geocoding ({lat}, {lon}): {e}")
        return None


def batch_reverse_geocode(gdf, api_key, batch_size=50, delay=2):
    """
    For each LineString in the GeoDataFrame, compute centroid,
    reverse geocode it with Google API, and add results as new columns.
    """
    # Always reproject to WGS84 for Google API
    if gdf.crs != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)

    gdf["centroid"] = gdf.geometry.centroid
    gdf["lat"] = gdf.centroid.y
    gdf["lon"] = gdf.centroid.x

    addresses = []

    for i, row in gdf.iterrows():
        lat, lon = row["lat"], row["lon"]
        address = reverse_geocode(lat, lon, api_key)
        addresses.append(address)

        # Pause every batch to avoid quota issues
        if (i + 1) % batch_size == 0:
            print(f"Processed {i+1} rows, pausing {delay}s...")
            time.sleep(delay)

    gdf["address"] = addresses
    return gdf

# ================================== Extract Street Names ====================================
def extract_street_name(address: str) -> str:
    """
    Extract street name from a Google Maps formatted address.
    Examples:
        "9 Abudu Oladejo St, Papa Ashafa, Lagos 102212, Lagos, Nigeria"
            -> "Abudu Oladejo St"
        "13b Peace Cl, Ifako Agege, Lagos 101232, Lagos, Nigeria"
            -> "Peace Cl"
        "11A Ajayi Rd, Ojodu, Ikeja 300001, Lagos, Nigeria"
            -> "Ajayi Rd"
        "Harmony Estate, 29 Kolapo Boluwade Cres, Ifako-Ijaiye, Lagos 101232, Lagos, Nigeria"
            -> "Kolapo Boluwade Cres"   # (if estate name comes first, we still extract street)
    """

    if not isinstance(address, str) or not address.strip():
        return ""

    # Split by comma -> take first chunk (sometimes has house number + street)
    parts = address.split(",")
    first_part = parts[0].strip()

    # Remove leading house numbers or unit identifiers
    cleaned = re.sub(r"^\s*\d+[A-Za-z\-]*\s+", "", first_part)

    # If cleaned result is empty (rare), just return the first part
    return cleaned if cleaned else first_part

# ================================== MAIN FUNCTION ==================================
def filter_non_intersecting_lines(first_data_filepath, second_data_filepath, api_key):
    """
    This generates the difference between two lines, the first being less complete than the second
    It checks for the lines that intersects and takes them out leaving the second lines that do not intersect with the first
    The difference is also plotted
    :param first_data_filepath: fewer linestrings
    :param second_data_filepath: the data with a lot of linestrings
    :param api_key: google api key
    :return: the difference between the 2 linestrings
    """

    # load layers from the first dataset
    layers = fiona.listlayers(first_data_filepath)
    gdf = [gpd.read_file(first_data_filepath, layer=lyr) for lyr in layers]
    print(f"The layers are {layers}")

    # Merge the layers in the first dataset into one GeoDataFrame
    gdf_1 = gpd.GeoDataFrame(pd.concat(gdf, ignore_index=True), crs=gdf[0].crs)

    # Load customer coverage lines
    gdf_2 = gpd.read_file(second_data_filepath)

    # Make sure they’re in the same CRS
    gdf_2 = gdf_2.to_crs(gdf_1.crs)
    info_first = gdf_1["geometry"].value_counts().sum()
    info_second = gdf_2["geometry"].value_counts().sum()
    print(f"The first data has {info_first} lines and the second data has {info_second} lines")

    # Break down MultiLineStrings into LineStrings so that the lines that can iterated individually
    gdf_1 = gdf_1.explode(index_parts=False, ignore_index=True)
    gdf_2= gdf_2.explode(index_parts=False, ignore_index=True)

    # Check for intersecting lines
    gdf_diff = gdf_2[~gdf_2.intersects(gdf_1.unary_union)]
    diff = gdf_diff["geometry"].value_counts().sum()
    print(f"There are {diff} lines from the second data that do not intersect with the first one")

    # Calculate distance and assign values to a field
    gdf_diff = gdf_diff.to_crs(epsg=32631)
    gdf_diff["distance_m"] = gdf_diff.geometry.length

    # ===== Reverse geocode centroids of non-intersecting lines =====
    gdf_diff = batch_reverse_geocode(gdf_diff, api_key)

    # Extract street name
    gdf_diff["name"] = gdf_diff["name"].fillna(gdf_diff["address"].apply(extract_street_name))

    # drop unncessary columns
    # drop multiple non-geometry columns safely
    cols_to_drop = ["centroid", "address"]  # replace with your unwanted columns
    gdf_diff = gdf_diff.drop(columns=cols_to_drop, errors="ignore")

    # ================== PLOT FINAL DIFFERENCE ==================
    # Create a map centered roughly on your data
    m = leafmap.Map(center=[6.45, 3.39], zoom=9, style="streets")

    # Style for non-right-of-way lines
    style_non_right = {"color": "blue", "weight": 2}

    # Style for right-of-way lines
    style_right = {"color": "red", "weight": 2}

    # Add the GeoDataFrames
    gdf_plot = gdf_diff.drop(columns=["centroid", "id", "code", "ref", "rid"], errors="ignore")
    m.add_gdf(gdf_plot, layer_type="line", layer_name="Non-Right-of-Way Roads", style=style_non_right)

    # Add right-of-way roads
    m.add_gdf(gdf_1, layer_type="line", layer_name="Right-of-Way Roads", style=style_right)

    # Zoom to fit both datasets
    m.zoom_to_gdf(pd.concat([gdf_diff, gdf_1]))

    return {"gdf": gdf_diff, "map": m}

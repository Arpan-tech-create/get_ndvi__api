from flask import Flask, render_template, request, send_file
import geopandas as gpd
import json
from io import BytesIO
from datetime import datetime
import pandas as pd
from tqdm import tqdm
import requests
import os

app = Flask(__name__, template_folder='templates')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_geojson', methods=['POST'])
def process_geojson():
    geojson_string = request.form['geojsonstring']
    columnName = request.form['columnName']

    # Convert GeoJSON string to a GeoDataFrame
    geojson_data = json.loads(geojson_string)
    gdf = gpd.GeoDataFrame.from_features(geojson_data['features'])

    

    # Server URL for field profile analysis
    url = 'http://192.168.2.64:55567/run_field_profile'

    # Initialize result and timestamp sets
    results = []
    timestamps = set()

    # Check if specified column exists in GeoDataFrame
    if columnName not in gdf.columns:
        return "Column name not found in the GeoJSON data.", 400 

    # Iterate over GeoDataFrame rows
    for idx, row in tqdm(gdf.iterrows(), total=len(gdf)):
        coordinates = list(row['geometry'].exterior.coords)

        # Create GeoJSON string for the current polygon
        geojson_string = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [coordinates]
                    },
                    "properties": None
                }
            ]
        }

        # Create payload for the POST request
        payload = json.dumps({
            'dset': 'NDVI_10D_S2_GUJ',
            'geojsonstring': json.dumps(geojson_string),
            'columnName': columnName,
        })

        try:
            # Send POST request to the server
            response = requests.post(url, data=payload, timeout=90, verify=False, headers={'Content-Type': 'application/json'})  
            data = response.json()

            # Process the response
            if isinstance(data, list):
                for entry in data:
                    timestamp_mill = entry[0]
                    timestamp = datetime.utcfromtimestamp(timestamp_mill / 1000).strftime('%d-%m-%Y')
                    ndvi = entry[1] / 250

                    timestamps.add(timestamp)

                    if columnName in row:
                        id = row[columnName]  
                        result = (id, timestamp, ndvi)
                        results.append(result)
                    else:
                        print(f"Column '{columnName}' not found in the GeoDataFrame.")
            else:
                print(f"Invalid response format from server: {data}")

        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err}")
        except Exception as err:
            print(f"An error occurred: {err}")

    # Organize results by polygon ID and timestamp
    organized_results = {polygon_id: {'ndvi_values': {}} for polygon_id in set(row[columnName] for _, row in gdf.iterrows())}

    for result in results:
        id, timestamp, ndvi = result
        organized_results[id]['ndvi_values'][timestamp] = ndvi

    # Prepare CSV rows
    csv_rows = []
    for polygon_id, data in organized_results.items():
        row = {'PolygonID': polygon_id}
        row.update({f'{timestamp}_NDVI': ndvi for timestamp, ndvi in data['ndvi_values'].items()})
        csv_rows.append(row)

    # Create a DataFrame from CSV rows
    csv_df = pd.DataFrame(csv_rows)

    # Save DataFrame to CSV
    output_csv_path = os.path.join(os.path.dirname(geojson_string.filename), 'output.csv')  # Specify the desired output path
    csv_df.to_csv(output_csv_path, index=False)

    return send_file(output_csv_path, as_attachment=True, download_name='output.csv')

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)

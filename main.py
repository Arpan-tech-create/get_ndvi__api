from flask import Flask, render_template, request, redirect, send_file
import geopandas as gpd
import requests
import json
import zipfile
import tempfile
from io import BytesIO
from tqdm import tqdm
from datetime import datetime
import shutil
import os
import pandas as pd

app = Flask(__name__, template_folder='templates')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_zip', methods=['POST'])
def process_zip():
    uploaded_file = request.files['file']
    if uploaded_file.filename != '' and uploaded_file.filename.endswith('.zip'):
        zip_content = BytesIO(uploaded_file.read())

        with zipfile.ZipFile(zip_content, 'r') as zip_ref:
            temp_dir = tempfile.mkdtemp()
            zip_ref.extractall(temp_dir)

            shapefile_paths = []
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file.endswith('.shp'):
                        shapefile_paths.append(os.path.join(root, file))

            if shapefile_paths:
                shapefile_path = shapefile_paths[0] 
                gdf = gpd.read_file(shapefile_path)
                gdf = gdf.to_crs('EPSG:4326')

                url = 'http://192.168.2.64:55567/run_field_profile'

                results = []
                timestamps = set()

                columnName = request.form.get('columnName') 
                if columnName not in gdf.columns:
                    return "Column name not found in the shapefile.", 400 

                for idx, row in tqdm(gdf.iterrows(), total=len(gdf)):
                    coordinates = list(row['geometry'].exterior.coords)

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

                    payload = json.dumps({
                        'dset': 'NDVI_10D_S2_GUJ',
                        'geojsonstring': json.dumps(geojson_string),
                        'columnName': columnName,
            
                    })

                    try:
                        response = requests.post(url, data=payload, timeout=90, verify=False, headers={'Content-Type': 'application/json'})  
                        data = response.json()

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
                                    print(f"Column '{columnName}' not found in the shapefile.")
                        else:
                            print(f"Invalid response format from server: {data}")

                    except requests.exceptions.HTTPError as http_err:
                        print(f"HTTP error occurred: {http_err}")
                    except Exception as err:
                        print(f"An error occurred: {err}")

               
                organized_results = {polygon_id: {'ndvi_values': {}} for polygon_id in set(row[columnName] for _, row in gdf.iterrows())}

                for result in results:
                    id, timestamp, ndvi = result
                    organized_results[id]['ndvi_values'][timestamp] = ndvi

               
                csv_rows = []
                for polygon_id, data in organized_results.items():
                    row = {'PolygonID': polygon_id}
                    row.update({f'{timestamp}_NDVI': ndvi for timestamp, ndvi in data['ndvi_values'].items()})
                    csv_rows.append(row)

    
                csv_df = pd.DataFrame(csv_rows)

                output_csv_path = os.path.join(os.path.dirname(uploaded_file.filename), 'output.csv')
                csv_df.to_csv(output_csv_path, index=False)

                shutil.rmtree(temp_dir)

                return send_file(output_csv_path, as_attachment=True, download_name='output.csv')
            else:
                shutil.rmtree(temp_dir)
                return "No shapefile found in the uploaded zip file.", 400
    return redirect('/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)







document.getElementById('file').addEventListener('change', function() {
    var file = this.files[0];
    var fileType = file.name.split('.').pop();
  
    if (fileType !== 'zip') {
      showErrorMsg('Invalid File Format');
      document.getElementById('submitBtn').style.display = 'none';
      return;
    }
  
    document.getElementById('uploadMsg').innerHTML = 'Uploaded: ' + file.name;
    document.getElementById('submitBtn').style.display = 'none'; 
    document.getElementById('columnName').addEventListener('input', function() {
      if (this.value.trim() !== '') {
        document.getElementById('submitBtn').style.display = 'block'; 
      } else {
        document.getElementById('submitBtn').style.display = 'none';
      }
    });
  });
  
  document.getElementById('submitBtn').addEventListener('click', function() {
    document.getElementById('submitBtn').style.display = 'none';
    document.getElementById('uploadMsg').innerHTML = 'Processing Zip File...';
  
    var file = document.getElementById('file').files[0];
    var columnName = document.getElementById('columnName').value; 
    var formData = new FormData();
    formData.append('file', file);
    formData.append('columnName', columnName); 
  
    fetch('/process_zip', {
      method: 'POST',
      body: formData
    })
    .then(response => {
      if (response.ok) {
        return response.blob();
      } else {
        return response.text().then(message => {
          throw new Error(message);
        });
      }
    })
    .then(blob => {
      var url = window.URL.createObjectURL(blob);
      document.getElementById('downloadBtn').style.display = 'block'; 
      document.getElementById('downloadBtn').href = url;
      document.getElementById('downloadBtn').download = 'output.csv'; 
      document.getElementById('uploadMsg').innerHTML = 'Processing Complete';
    })
    .catch(error => {
      console.error('Error:', error);
      document.getElementById('uploadMsg').innerHTML = error.message;
    });
  });
  
  function showErrorMsg(msg) {
    var uploadMsg = document.getElementById('uploadMsg');
    uploadMsg.innerHTML = msg;
    uploadMsg.style.color = 'red';
  }



  
  <!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>GET NDVI</title>
  <link rel="stylesheet" type="text/css" href="{{ url_for('static', filename='css/style.css') }}">

</head>
<body>
  <h1>NDVI Temporal Profile Download Tool</h1>
  <h3>Upload a Zip File that contains polygons of Interest</h3>


  <form id="uploadForm" enctype="multipart/form-data">
    <label for="file" class="custom-file-upload">Select File</label>
    <input type="file" name="file" id="file" accept=".zip">
    <br>
    <label for="columnName">Column Name:</label>
    <input type="text" name="columnName" id="columnName" required>
    <div id="uploadMsg" class="upload-msg"></div>
    <center>
      <button type="button" id="submitBtn" class="submit-btn" style="display:none;">Submit</button>
    </center>
    <a id="downloadBtn" style="display:none;">Download Data</a>
  </form>


  

  
  <script src="{{url_for('static',filename='js/custom.js')}}"></script>
</body>
</html>

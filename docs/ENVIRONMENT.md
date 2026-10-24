# Environment

## Summary

| Item | Requirement |
|---|---|
| Language | Python 2.7 |
| Software | ArcGIS Desktop / ArcMap 10.8 |
| Operating system | Windows (required by ArcGIS Desktop) |
| Required library | ArcPy, installed with ArcGIS Desktop |
| Optional libraries | reportlab (PDF report), matplotlib and numpy (report charts) |

ArcMap 10.8 ships with its own Python 2.7. The toolbox must run with that interpreter. A separate Python 3 installation, a conda environment or a virtual environment cannot be used, because ArcPy for ArcMap is not available there.

## Check the installation

Open the Python window in ArcMap (Geoprocessing menu, then Python) and run:

```python
import sys, arcpy
print(sys.version)
print(arcpy.GetInstallInfo()["Version"])
```

The first line should show Python 2.7 and the second should show 10.8.

## Install the optional reportlab library

1. Close ArcMap.
2. Open Command Prompt as Administrator.
3. Run the pip that belongs to ArcGIS (the default install path is shown below):

```
C:\Python27\ArcGIS10.8\python.exe -m pip install reportlab
```

If `pip` is not found, run `C:\Python27\ArcGIS10.8\python.exe -m ensurepip` first, or install the package from a downloaded wheel file.

4. Reopen ArcMap and run the tool with **Generate Statistical Summary Report** switched on.

If reportlab is missing, the tool still completes and writes the report as a plain-text file, with a message in the tool dialog.

## Install the optional charts libraries

The five report charts need `matplotlib` and `numpy`. They may already be present in your ArcGIS Python. If the tool prints a warning that matplotlib is missing, install it once. The last matplotlib version that supports Python 2.7 is 2.2.5:

```
C:\Python27\ArcGIS10.8\python.exe -m pip install "matplotlib==2.2.5" numpy
```

If matplotlib is missing the report is still produced in full, only without charts. A failure in any single chart is also skipped without stopping the run.

Charts are saved as PNG, PDF and SVG in a `charts` folder inside the report output folder, and the PNG files are embedded in the PDF.

## Add the toolbox in ArcMap

1. Open the Catalog window or ArcToolbox.
2. Right-click **ArcToolbox**, choose **Add Toolbox** and select `toolbox/Road_Features_Classification.pyt`.
3. Open **Automated Road Features Classification**.

Keep `Road_Features_Classification.pyt` and `Road_Features_Classification.pyt.xml` in the same folder.

## Input data requirements

| Input | Requirement |
|---|---|
| NHA roads | Polyline layer with a `Name` field containing route codes (M-, N-, S-) |
| OSM roads | Polyline layer with a functional class field such as `fclass` |
| Coordinate system | Projected (for example UTM 41N, 42N or 43N) for accurate distances. If the inputs are geographic, choose a projected system in the tool |
| Output | A file geodatabase, plus a folder for the report |

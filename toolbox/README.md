# Toolbox folder

This folder holds the ArcGIS Python Toolbox:

```
toolbox/
├── Road_Features_Classification.pyt        <- the tool source code
└── Road_Features_Classification.pyt.xml    <- ArcGIS metadata
```

Keep both files in the same folder with the same base name, so ArcGIS can read the toolbox and its metadata together.

**Requirements:** ArcGIS Desktop / ArcMap 10.8 (Python 2.7 with ArcPy). Optional: `reportlab` for the PDF report and `matplotlib` with `numpy` for the charts. See [../docs/ENVIRONMENT.md](../docs/ENVIRONMENT.md).

**Tool name in ArcToolbox:** Road Features Classification Toolbox, containing the single tool "Automated Road Features Classification".

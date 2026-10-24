# Methodology

## NHA route-code classification

`NHA_Class` is derived from the route-code prefix at the start of the `Name` field.

| Name prefix | NHA_Class | Example |
|---|---|---|
| M followed by digits | Motorway | M-2 |
| N followed by digits | National Highway | N-5 |
| S followed by digits | Strategic | S-1 |
| No recognised prefix | Review | needs manual attention |

Known non-numbered routes are matched by a case-insensitive substring rule list: `Lowari Tunnel` and `Lahore Eastern Bypass` / `LEBP` (National Highway), and `NIIA` (National Highway, access road). A manual override dictionary (keyed by OID or exact Name) always takes precedence over automated rules.

## OSM class mapping

| OSM fclass | Road_Class |
|---|---|
| motorway, motorway_link | Motorway |
| trunk, trunk_link | Trunk |
| primary, primary_link | Primary |
| secondary, secondary_link | Secondary |
| tertiary, tertiary_link | Tertiary |
| residential / service / unclassified | Residential / Service / Unclassified |

Unmapped values are labelled Other and logged, never silently dropped. Only motorway, trunk, primary and their link variants are used for matching.

## Spatial matching

1. OSM roads are first filtered by class (motorway, trunk, primary and their link variants).
2. Only OSM features within (3 x matching tolerance + 50 m) of any NHA feature are kept. With the default 10 m tolerance this is 80 m.
3. `Generate Near Table` (planar method, `closest = ALL`, no limit on count) returns every OSM feature within the matching tolerance of each NHA feature. Direction is ignored and exact overlap is not required.
4. Rows with null or zero-length geometry are removed from the working copies first.

The tool needs a projected coordinate system. It uses the one supplied, otherwise the NHA layer's, otherwise the OSM layer's, and stops with an error if both layers are geographic and none is supplied.

## Match status

| Status | Meaning |
|---|---|
| Unmatched | No OSM feature within tolerance |
| Matched | One OSM match, and its class agrees with the NHA class |
| Multiple | More than one OSM match, and at least one agrees by class |
| Matched (Name Confirmed) | No class agreement, but the route code (for example `M-2` and `M2`) is identical between the NHA name and OSM `ref` or `name` |
| Conflict | Matches exist, no class agreement and no route-code agreement |
| SevereMismatch | A Conflict where an OSM match is Residential, Service or Unclassified |

`Final_Class` always equals `NHA_Class` (Motorway, National Highway, Review or Other). Match status never changes it.

## Road name

`Road_Name` starts from the NHA name. If the best-matched OSM feature has a different route code, its name or ref is appended, for example `N-85 (OSM: M-2)`. If the codes agree, or there is no OSM match, the plain NHA name is used. `Road_Type` repeats `Final_Class`.

## Agreement, conflict and severe mismatch

- NHA Motorway agrees only with OSM Motorway.
- NHA National Highway agrees with OSM Trunk, Primary or Motorway.
- Any other matched pair is a **Conflict**.
- An NHA Motorway or National Highway matched only to an OSM Residential, Service or Unclassified road is a **Severe Mismatch**.

Name and route-code agreement is supporting evidence only. It can upgrade a match to "Matched (Name Confirmed)" but is never proof on its own.

## Report thresholds (defaults)

| Setting | Value |
|---|---|
| Matching tolerance (tool parameter) | 10 m |
| Overlap tolerance | 5 m |
| Overlapping tier | At least 99% of NHA length within the overlap tolerance of the matched OSM line |
| Partial-overlap threshold | 10% of NHA length |
| Alignment tiers | 5 m (High), 15 m (Slight), 50 m (Significant); each requires at least 60% of NHA length within tolerance |
| Positional accuracy tolerance | 10 m |

## Scope

By default `X05_Final_Road_Classification` and `Classification_Summary` contain only Motorway and National Highway features. Strategic roads and Review features are still computed and stay visible in the earlier working tables.

## Report sections

1. Dataset inventory and baseline statistics
2. Name and attribute matching
3. Geographic and spatial matching
4. Geometric alignment assessment
5. High-confidence match identification
6. Road classification agreement
7. Mismatch and error analysis
8. NHA network completeness in OSM
9. Length-based network comparison
10. OSM feature fragmentation
11. Spatial accuracy and positional deviation
12. Overall classification and data quality assessment
13. Methodological notes and limitations

## Figures

| Figure | File |
|---|---|
| Tool dialog | `images/fig01_tool_dialog.png` |
| Toolbox header | `images/fig02_toolbox_header.png` |
| execute() excerpt | `images/fig03_execute_method.png` |
| Progress: OSM pre-filter | `images/fig04_progress_prefilter.png` |
| Progress: completion | `images/fig05_progress_complete.png` |
| Final output in ArcMap | `images/fig06_arcmap_final_output.png` |
| Report opening | `images/fig07_report_opening.png` |
| NHA dataset composition | `images/fig08_nha_dataset_composition.png` |
| Attribute/name agreement | `images/fig09_attribute_name_agreement.png` |
| Spatial correspondence | `images/fig10_spatial_correspondence.png` |
| Classification agreement | `images/fig11_classification_agreement.png` |

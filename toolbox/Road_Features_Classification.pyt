# -*- coding: utf-8 -*-
"""
================================================================================
 Road_Features_Classification.pyt
================================================================================
PURPOSE
    Single-click, end-to-end classification and cross-comparison of
    Motorway / National Highway road features between the authoritative
    NHA (National Highway Authority) dataset and the OSM (OpenStreetMap)
    roads dataset. This is ONE tool (not a multi-tool toolbox) - every
    stage below runs in a single execution of "Automated Road Features
    Classification".

    Given only the two ORIGINAL input layers, this tool performs:
        1. Safe copy of inputs into a working output geodatabase
           (originals are NEVER modified).
        2. Automated classification of NHA roads (NHA_Class, NHA_Category,
           CPEC_Flag) based on explicit, editable rules.
        3. Automated classification of OSM roads (Road_Class) based on an
           explicit, editable fclass mapping dictionary.
        4. Spatial matching of NHA roads to nearby OSM roads using
           Generate Near Table (line-to-line proximity matching, tolerance
           configurable, does not require exact overlap or direction match).
        5. Comparison of NHA vs OSM classification per match, producing
           Match_Count / Match_Status / OSM_Match_ID / OSM_Class fields.
        6. Determination of a Final_Class per NHA feature, using NHA as the
           authoritative source; OSM used only for verification/QC, never to
           silently override NHA.
        7. Production of a full traceable output feature class plus a
           Classification_Summary diagnostic table.
        8. (Optional, on by default) A comprehensive thirteen-section
           Final Statistical Summary report comparing NHA and OSM -
           inventory, name/attribute matching, spatial matching tiers,
           geometric alignment, Perfect Match identification,
           classification agreement, mismatch taxonomy, network
           completeness, length comparison, fragmentation, positional
           accuracy, an overall data-quality assessment, and a closing
           methodological notes/limitations section - exported as
           a formatted PDF (falls back to a plain-text file with a clear
           on-screen instruction if the optional 'reportlab' PDF library
           is not installed in this ArcGIS Python environment).

AUTHOR
    Faseeh Tahir - Survey of Pakistan Internship Project

ARCGIS VERSION
    ArcGIS Desktop 10.8 / ArcMap 10.8 (NOT ArcGIS Pro)

PYTHON VERSION
    Python 2.7 (as shipped with ArcMap 10.8). No Python 3 syntax is used
    anywhere in this file (no f-strings, no pathlib, no type annotations).
    The PDF report step uses the optional third-party 'reportlab'
    package (pure-Python, no compiled dependencies) - see the
    write_statistical_report_pdf() docstring for the one-time install
    command. Every other part of this tool uses only ArcPy and the
    Python 2.7 standard library.

INPUTS
    - NHA polyline feature layer (original, untouched)
    - OSM polyline feature layer (original, untouched)
    - Output File Geodatabase (created by user beforehand in ArcCatalog,
      or an existing one)
    - Optional: matching tolerance, field overrides, projected coordinate
      system, diagnostic output toggle, PDF report toggle + output folder
      + positional accuracy tolerance

OUTPUTS (all inside the chosen Output Geodatabase, produced in one run)
    X01_NHA_Prepared            - working copy of NHA with classification fields
    X02_OSM_Prepared            - working copy of relevant OSM roads with Road_Class
    X03_NHA_OSM_NearTable       - raw Generate Near Table output (diagnostic only)
    X04_NHA_OSM_Comparison      - one row per NHA feature x matched OSM feature
    X05_Final_Road_Classification - one row per NHA feature, final authoritative
                                     output with all traceability fields
    Classification_Summary      - pivot-style summary table (counts by class/status)
    Stat_NameAttributeMatch, Stat_SpatialMatchTiers, Stat_GeometricAlignment,
    Stat_ClassificationMatrix   - per-feature detail tables backing the PDF report

    PLUS, in the chosen Report Output Folder:
    Final_Statistical_Summary_NHA_vs_OSM.pdf (or .txt fallback)

WORKFLOW TRACEABILITY
    Final_Class (Motorway / National Highway / Other / Review - a CLEAN
    classification label only, never a QC term)
        <- NHA_Class (authoritative)
        <- OSM_Match_ID, OSM_Class (supporting evidence)
        <- Match_Status (Matched / Matched (Name Confirmed) / Conflict /
                          SevereMismatch / Unmatched / Multiple - the QC
                          signal, kept separate from Final_Class so the
                          classification label is never confused with the
                          confidence/agreement indicator)
        <- Match_Count (how many OSM segments corresponded spatially)
    Every one of these fields is retained in 05_Final_Road_Classification so
    any result can be traced back through the pipeline without re-running it.

OUTPUT SCOPE
    05_Final_Road_Classification and Classification_Summary contain ONLY
    Motorway and National Highway features by default (see
    FINAL_OUTPUT_CLASSES / RESTRICT_FINAL_OUTPUT_TO_SCOPE). Strategic
    roads and unresolved 'Review' features are still fully computed and
    remain visible in 01_NHA_Prepared and 04_NHA_OSM_Comparison - nothing
    is silently discarded upstream, it is simply kept out of the two
    final, scope-restricted deliverables.

IMPORTANT ASSUMPTIONS (see also inline comments at each rule / and the
    accompanying chat explanation "STEP 2 - Assumptions"):
    1. NHA Name field is parsed for leading route-code prefixes (M-, N-, S-)
       to assign NHA_Class. Anything that does not match a known prefix is
       assigned 'Review', NOT silently classified as 'Other'.
    2. CPEC_Flag is derived only from FolderPath containing 'CPEC' and never
       affects NHA_Class.
    3. Only OSM fclass values considered potentially relevant to Motorway /
       National Highway comparison are carried into 02_OSM_Prepared
       (see OSM_RELEVANT_FCLASS below). This is a PERFORMANCE + RELEVANCE
       filter, not a final classification. It is applied BEFORE matching.
    4. Generate Near Table is used with closest='ALL' (return every
       candidate within tolerance, not just the single nearest) so that
       legitimate multiple-segment matches (Match_Count > 1) are preserved
       rather than collapsed to a single nearest feature.
    5. Distance-based matching requires a projected coordinate system. If
       inputs are geographic, the user MUST supply a projected coordinate
       system parameter; the tool does not silently guess a UTM zone because
       Pakistan spans multiple UTM zones (41N/42N/43N).
    6. Road-class agreement (NHA_OSM_AGREEMENT) can be reinforced, but never
       replaced, by route-code (name/ref) matching between NHA Name and OSM
       ref/name - see Section A.3.1. This satisfies "match by combining
       both layers' names" while keeping name/ref as supporting evidence
       only, never the sole matching criterion, per the original spec.
    7. Rows with null/empty geometry in the working copies are removed
       before classification/matching (see remove_null_geometry()) - this
       never touches the original input layers.
================================================================================
"""

import arcpy
import os
import sys
import traceback
import re
import io

# ------------------------------------------------------------------------
# arcpy.env settings
# ------------------------------------------------------------------------
# We allow overwriting of intermediate/output datasets that THIS toolbox
# creates inside the user-selected output geodatabase, so the tool can be
# re-run repeatedly on the same output GDB without manual cleanup.
# This does NOT affect the original NHA / OSM input layers, which are only
# ever read from, never written to.
arcpy.env.overwriteOutput = True


# ==========================================================================
# SECTION A: CONFIGURATION - EDIT THESE TO CHANGE CLASSIFICATION BEHAVIOUR
# ==========================================================================
#
# Everything in this section is a deliberately isolated, human-editable
# rule set. Nothing below this section should need to change if you only
# want to adjust classification logic.

# --------------------------------------------------------------------
# A.1 NHA classification rules
# --------------------------------------------------------------------
# NHA_Class is derived primarily from the route-code prefix at the start
# of the Name field (after stripping whitespace). This mirrors how NHA
# itself names its routes (M-#, N-#, S-#) and matches the manually
# corrected 'NHA_class' field the user previously built by hand.
#
# NOTE: This is a PREFIX match on the Name field, e.g. "N-5 (Torkham-
# Karachi)" -> prefix "N-5" -> matches pattern for National Highway.
#
# If you need to hard-code specific corrections (mirroring manual fixes
# you have already made in your own 'NHA_class' field), add them to
# NHA_MANUAL_OVERRIDES below using the NHA OID or exact Name string.
# Manual overrides ALWAYS win over the regex rules.

NHA_MOTORWAY_PATTERN = re.compile(r'^\s*M[\s\-]?\d+', re.IGNORECASE)
NHA_NATIONAL_HIGHWAY_PATTERN = re.compile(r'^\s*N[\s\-]?\d+', re.IGNORECASE)
NHA_STRATEGIC_PATTERN = re.compile(r'^\s*S[\s\-]?\d+', re.IGNORECASE)

# Known non-numbered special named routes and how they should classify.
# Add more names here as you discover them (e.g. "Lowari Tunnel").
# Matching is case-insensitive and uses "contains", not exact match.
NHA_NAMED_ROUTE_RULES = [
    # (substring to search for in Name, NHA_Class, NHA_Category)
    ("Lowari Tunnel", "National Highway", "Tunnel"),
    ("Lahore Eastern Bypass", "National Highway", "Bypass"),
    ("LEBP", "National Highway", "Bypass"),
    ("NIIA", "National Highway", "Access Road"),
]

# Manual overrides: fill this dictionary with corrections you already know
# about from your manually-built 'NHA_class' field. Key can be either the
# NHA OID (integer) or the exact Name string (string). OID keys take
# priority over Name keys if both are present for the same feature.
# Example:
#   NHA_MANUAL_OVERRIDES = {
#       42: ("Motorway", "Verified Manual Correction"),
#       "N-455": ("National Highway", "Verified Manual Correction"),
#   }
NHA_MANUAL_OVERRIDES = {
    # <-- ADD YOUR KNOWN MANUAL CORRECTIONS HERE -->
}

# FolderPath values used ONLY to populate CPEC_Flag (informational),
# never used to determine NHA_Class.
CPEC_FOLDER_KEYWORD = "CPEC"

# --------------------------------------------------------------------
# A.2 OSM classification mapping
# --------------------------------------------------------------------
# Explicit fclass -> Road_Class mapping. Add/edit entries here.
# Any fclass value encountered that is NOT in this dictionary will be
# classified as 'Other' and a warning will be logged (not silently
# dropped), so unexpected OSM fclass values are always visible to you.
OSM_CLASS_MAPPING = {
    'motorway': 'Motorway',
    'motorway_link': 'Motorway',
    'trunk': 'Trunk',
    'trunk_link': 'Trunk',
    'primary': 'Primary',
    'primary_link': 'Primary',
    'secondary': 'Secondary',
    'secondary_link': 'Secondary',
    'tertiary': 'Tertiary',
    'tertiary_link': 'Tertiary',
    'residential': 'Residential',
    'service': 'Service',
    'unclassified': 'Unclassified',
}

# OSM fclass values that are pulled into the working OSM layer for
# matching purposes. This is a PERFORMANCE / RELEVANCE pre-filter applied
# BEFORE spatial matching, to avoid dragging all ~299,043 OSM features
# (including e.g. service/residential roads) through the near-table
# computation. Only classes plausibly relevant to Motorway / National
# Highway comparison are included.
#
# ASSUMPTION (flagged explicitly): this means an OSM 'secondary' or
# lower-class road can NEVER appear as a match, even if it happens to be
# the nearest feature within tolerance. If you want to allow matching
# against lower OSM classes (e.g. to catch cases where a Motorway was
# mis-tagged as 'secondary' in OSM), add those fclass values here.
OSM_RELEVANT_FCLASS = ['motorway', 'motorway_link', 'trunk', 'trunk_link',
                        'primary', 'primary_link']

# --------------------------------------------------------------------
# A.3 Conflict / agreement rules (NHA_Class vs OSM_Class)
# --------------------------------------------------------------------
# Defines which OSM_Class values are considered to AGREE with a given
# NHA_Class. Anything matched but not in the "agree" set is a Conflict.
NHA_OSM_AGREEMENT = {
    'Motorway': ['Motorway'],
    'National Highway': ['Trunk', 'Primary', 'Motorway'],
}

# OSM_Class values that, if matched against an NHA Motorway or National
# Highway feature, indicate a LIKELY OSM DATA ERROR worth flagging
# distinctly (rather than a generic conflict). These should not normally
# occur given OSM_RELEVANT_FCLASS above, but are checked as a safety net
# in case OSM_RELEVANT_FCLASS is edited later.
NHA_OSM_SEVERE_MISMATCH = ['Residential', 'Service', 'Unclassified']

# --------------------------------------------------------------------
# A.3.1 Route-code (name/ref) cross-matching - SUPPORTING evidence only
# --------------------------------------------------------------------
# Both NHA (e.g. "N-5 (Torkham-Karachi)", "M-2 (Lahore-Islamabad)") and
# OSM (via the 'ref' field, e.g. "N5", "M2", sometimes also in 'name')
# carry a route-code token. This is used ONLY as supporting evidence to
# resolve an otherwise-ambiguous spatial Conflict - it is explicitly NOT
# allowed to be the sole basis of a match, per the original specification
# ("road name/ref can be used as supporting evidence, but should NOT be
# the sole matching criterion"). A route-code match can upgrade a
# spatially-matched 'Conflict' to 'Matched (Name Confirmed)' but can
# NEVER create a match where no spatial proximity match already exists,
# and can NEVER override NHA_Class.
#
# The route-code token is normalised by: uppercasing, stripping all
# whitespace and hyphens, e.g. "N-5" -> "N5", "M -2" -> "M2", "N5" -> "N5".
ROUTE_CODE_PATTERN = re.compile(r'^([MNS])[\s\-]?(\d+)', re.IGNORECASE)


def extract_route_code(text_value):
    """
    Extracts a normalised route code token (e.g. 'N5', 'M2') from a text
    field (NHA Name, or OSM ref/name). Returns None if no route-code-like
    pattern is found. Used only as SUPPORTING evidence (see A.3.1 above).
    """
    if not text_value:
        return None
    match = ROUTE_CODE_PATTERN.match(text_value.strip())
    if not match:
        return None
    letter = match.group(1).upper()
    number = match.group(2)
    return letter + number


def _clean_display_name(raw_value):
    """Trims a raw Name/ref value for display; returns None for blank/
    missing input rather than an empty string, so callers can use a
    simple truthiness check."""
    if raw_value is None:
        return None
    cleaned = raw_value.strip()
    return cleaned if cleaned else None


def build_road_name(nha_name_raw, nha_route_code, osm_display_raw,
                     osm_route_code):
    """
    Builds the Road_Name value written to X05_Final_Road_Classification
    and Stat_NameAttributeMatch for one NHA feature, per the project
    requirement to name every road in the final layer using both NHA
    (the reference layer) and its matched OSM feature.

    NHA is always the authoritative source for the name itself (NHA is
    the reference dataset throughout this tool - see Section 13(a) of
    the report), so Road_Name always starts from the NHA Name value.
    The matched OSM feature's own name/ref is appended in parentheses
    ONLY when it is a genuinely different route designation from NHA's
    - e.g. an NHA feature named 'N-85' whose best-matched OSM segment is
    tagged ref='M-2' becomes Road_Name = 'N-85 (OSM: M-2)', so the
    discrepancy between the two datasets is visible directly in the
    final layer without cross-referencing OSM_Class/Match_Status
    separately. When the two datasets' route codes already agree (e.g.
    NHA 'N-5' vs OSM ref 'N5', or no OSM match exists at all), Road_Name
    is simply the clean NHA name with no redundant OSM echo.

    Returns a plain string, never None (falls back to a placeholder for
    the rare case of a genuinely blank NHA Name field, so Road_Name is
    never left null in the output).
    """
    nha_display = _clean_display_name(nha_name_raw) or "Unnamed NHA Feature"
    osm_display = _clean_display_name(osm_display_raw)

    if not osm_display:
        return nha_display

    # Route codes normalise to the same value (even if formatted
    # differently, e.g. 'M-2' vs 'M2') - the two datasets already agree,
    # so appending OSM's raw string would just be a redundant echo.
    if nha_route_code and osm_route_code and nha_route_code == osm_route_code:
        return nha_display

    return "%s (OSM: %s)" % (nha_display, osm_display)


# --------------------------------------------------------------------
# A.3.2 Output scope - which NHA_Class values appear in the final output
# --------------------------------------------------------------------
# Per project scope, only Motorway and National Highway are of interest
# for the final deliverable. Strategic roads, and any NHA feature that
# could not be confidently classified ('Review'), are still fully
# computed and available for inspection in X01_NHA_Prepared and
# X04_NHA_OSM_Comparison (nothing is silently discarded upstream), but
# are EXCLUDED from X05_Final_Road_Classification and
# Classification_Summary by default so those two deliverables stay
# focused on the roads you actually asked to classify.
#
# Set this to False if you want Strategic/Review features included in
# the final output and summary as well (e.g. for a full QC pass).
FINAL_OUTPUT_CLASSES = ['Motorway', 'National Highway']
RESTRICT_FINAL_OUTPUT_TO_SCOPE = True

# --------------------------------------------------------------------
# A.4 Final classification decision table
# --------------------------------------------------------------------
# IMPORTANT DESIGN CHOICE (revised after initial user review):
# Final_Class is now kept as a CLEAN, NHA-authoritative label only -
# it is set equal to NHA_Class and is NEVER 'Conflict', 'Review',
# 'Unmatched' or any other QC term. Those QC signals live exclusively in
# Match_Status (and QC_Note), so a person scanning Final_Class sees only
# real classification labels, while a person who wants to audit
# confidence looks at Match_Status separately. This directly answers
# the question "what's the sense behind Conflict/Review appearing in
# Final_Class?" - it was a UX mistake in the first version; it does not
# happen anymore.
#
# Human-readable summary of the Final_Class decision logic implemented in
# determine_final_class() below:
#
#   NHA_Class is 'Review'                     -> Final_Class = 'Review'
#                                                 (still explicit: an
#                                                  automated pipeline must
#                                                  never invent a Motorway/
#                                                  National Highway label
#                                                  for a feature it could
#                                                  not confidently name)
#   NHA_Class is 'Motorway' or 'National Highway' (regardless of
#   Match_Status - Matched/Multiple/Conflict/Unmatched all keep NHA_Class)
#                                              -> Final_Class = NHA_Class
#   NHA_Class is 'Strategic' or anything else -> Final_Class = 'Other'
#
# Match_Status is ALWAYS retained alongside Final_Class in the output so
# a 'Motorway' row that had a spatial Conflict with OSM remains fully
# visible and auditable - it is simply no longer confused with the
# classification label itself.
#
# OSM NEVER overrides NHA_Class. OSM only ever changes Match_Status /
# QC flags. This directly implements the requirement in section 12 of the
# specification: "Do NOT allow OSM to automatically override authoritative
# NHA classification without a clearly documented rule."

# --------------------------------------------------------------------
# A.5 Field name constants (kept centralised for safety / consistency)
# --------------------------------------------------------------------
FLD_NHA_CLASS = "NHA_Class"
FLD_NHA_CATEGORY = "NHA_Category"
FLD_CPEC_FLAG = "CPEC_Flag"
FLD_OSM_CLASS = "Road_Class"
FLD_MATCH_COUNT = "Match_Count"
FLD_MATCH_STATUS = "Match_Status"
FLD_OSM_MATCH_ID = "OSM_Match_ID"
FLD_OSM_MATCH_CLASS = "OSM_Class"
FLD_FINAL_CLASS = "Final_Class"
FLD_NHA_SRC_OID = "NHA_Src_OID"
FLD_QC_NOTE = "QC_Note"
FLD_ROAD_NAME = "Road_Name"
FLD_ROAD_TYPE = "Road_Type"


# --------------------------------------------------------------------
# A.6 Statistical Summary Report - thresholds and weights
# --------------------------------------------------------------------
# These thresholds define the tiers used ONLY by the Statistical Summary
# tool (Tool 2) - they do not affect the classification/matching outputs
# produced by Tool 1. All are explicit and editable so the report's
# definitions of "perfect", "slight", "significant" etc. are never a
# hidden black box.

# --- Geometric alignment tiers (buffer-based) ---
# An NHA line is buffered by each of these distances in turn; the % of
# the NHA line's length that falls within an equivalently-buffered OSM
# corridor determines the alignment tier. This measures how closely the
# OSM geometry follows the NHA alignment, independent of Match_Status
# (which is about classification agreement, not geometric closeness).
ALIGNMENT_PERFECT_TOLERANCE = "5 Meters"     # within this -> "Perfect"
ALIGNMENT_SLIGHT_TOLERANCE = "15 Meters"     # within this -> "Slight Deviation"
ALIGNMENT_SIGNIFICANT_TOLERANCE = "50 Meters"  # within this -> "Significant Deviation"
# Beyond ALIGNMENT_SIGNIFICANT_TOLERANCE (and matched) -> "Misaligned"
# No spatial match at all -> "Not Assessable" (reported separately)
ALIGNMENT_MIN_COVERAGE_PCT = 60.0
# The minimum % of an NHA line's length that must fall within a given
# tolerance buffer of OSM geometry for that tolerance tier to "count".
# Chosen conservatively so a short coincidental overlap near one end of
# a long NHA route does not get scored as well-aligned; a route must be
# substantially covered, not just brushed, to earn a tier.

# --- Spatial matching tiers (independent of Match_Status classes) ---
SPATIAL_OVERLAP_TOLERANCE = "5 Meters"      # essentially coincident
SPATIAL_PARTIAL_MIN_PCT = 10.0               # >=10% length overlap -> Partial
SPATIAL_NEARBY_TOLERANCE = "100 Meters"      # near but not overlapping

# --- Perfect Match composite criteria ---
# An OSM feature (paired to its matched NHA feature) is counted as a
# "Perfect Match" only if ALL of the following hold simultaneously:
#   - Road class agrees (per NHA_OSM_AGREEMENT, i.e. Match_Status in
#     ('Matched','Multiple','Matched (Name Confirmed)'))
#   - Geometric alignment tier is 'Perfect' (see ALIGNMENT_* above)
#   - Route code (name/ref) either agrees or is not determinable on
#     either side (i.e. it must not actively DISAGREE)
PERFECT_MATCH_ALIGNMENT_TIERS = ['Perfect']

# --- Positional deviation ---
POSITIONAL_TOLERANCE_METERS = 10.0
# Used for "% of features within tolerance" in the positional accuracy
# statistics (requirement #11). Independent of the matching tolerance
# used by Tool 1's Generate Near Table (which controls candidate search
# radius, not reporting).


# ==========================================================================
# SECTION B: TOOLBOX / TOOL DEFINITION
# ==========================================================================

class Toolbox(object):
    def __init__(self):
        self.label = "Road Features Classification Toolbox"
        self.alias = "RoadFeaturesClassification"
        self.tools = [RoadClassificationTool]


class RoadClassificationTool(object):
    def __init__(self):
        self.label = "Automated Road Features Classification"
        self.description = (
            "End-to-end NHA vs OSM road classification pipeline: "
            "classifies NHA Motorway/National Highway features, "
            "classifies OSM road features, spatially matches them, "
            "compares classifications, produces a final authoritative "
            "classification with full QC traceability, and generates a "
            "comprehensive Final Statistical Summary PDF report."
        )
        self.canRunInBackground = False

    # ----------------------------------------------------------------
    def getParameterInfo(self):

        p_nha = arcpy.Parameter(
            displayName="NHA Input Layer",
            name="nha_input",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input")
        p_nha.filter.list = ["Polyline"]

        p_osm = arcpy.Parameter(
            displayName="OSM Input Layer",
            name="osm_input",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input")
        p_osm.filter.list = ["Polyline"]

        p_out_gdb = arcpy.Parameter(
            displayName="Output Geodatabase",
            name="output_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input")
        p_out_gdb.filter.list = ["Local Database"]

        p_tolerance = arcpy.Parameter(
            displayName="Matching Tolerance",
            name="matching_tolerance",
            datatype="GPLinearUnit",
            parameterType="Optional",
            direction="Input")
        p_tolerance.value = "10 Meters"

        p_nha_name_field = arcpy.Parameter(
            displayName="NHA Name Field",
            name="nha_name_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input")
        p_nha_name_field.parameterDependencies = ["nha_input"]

        p_nha_folder_field = arcpy.Parameter(
            displayName="NHA FolderPath Field",
            name="nha_folderpath_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input")
        p_nha_folder_field.parameterDependencies = ["nha_input"]

        p_osm_class_field = arcpy.Parameter(
            displayName="OSM Classification Field",
            name="osm_class_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input")
        p_osm_class_field.parameterDependencies = ["osm_input"]

        p_create_diagnostics = arcpy.Parameter(
            displayName="Create Diagnostic Outputs",
            name="create_diagnostics",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        p_create_diagnostics.value = True

        p_projected_crs = arcpy.Parameter(
            displayName=("Projected Coordinate System for Distance "
                         "Matching (required only if inputs are in a "
                         "geographic/unprojected coordinate system)"),
            name="projected_crs",
            datatype="GPSpatialReference",
            parameterType="Optional",
            direction="Input")

        p_generate_report = arcpy.Parameter(
            displayName="Generate Final Statistical Summary Report (PDF)",
            name="generate_report",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        p_generate_report.value = True

        p_report_folder = arcpy.Parameter(
            displayName="Report Output Folder",
            name="report_folder",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input")

        p_positional_tolerance = arcpy.Parameter(
            displayName="Positional Accuracy Tolerance (for the report's "
                         "spatial accuracy section)",
            name="positional_tolerance",
            datatype="GPLinearUnit",
            parameterType="Optional",
            direction="Input")
        p_positional_tolerance.value = "10 Meters"

        params = [p_nha, p_osm, p_out_gdb, p_tolerance, p_nha_name_field,
                  p_nha_folder_field, p_osm_class_field,
                  p_create_diagnostics, p_projected_crs,
                  p_generate_report, p_report_folder,
                  p_positional_tolerance]
        return params

    # ----------------------------------------------------------------
    def isLicensed(self):
        return True

    # ----------------------------------------------------------------
    def updateParameters(self, parameters):
        # Auto-detect NHA Name field
        nha_param = parameters[0]
        name_field_param = parameters[4]
        folder_field_param = parameters[5]

        if nha_param.value and not name_field_param.altered:
            try:
                fields = [f.name for f in arcpy.ListFields(nha_param.value)]
                if "Name" in fields:
                    name_field_param.value = "Name"
            except Exception:
                pass

        if nha_param.value and not folder_field_param.altered:
            try:
                fields = [f.name for f in arcpy.ListFields(nha_param.value)]
                if "FolderPath" in fields:
                    folder_field_param.value = "FolderPath"
            except Exception:
                pass

        # Auto-detect OSM classification field (default fclass)
        osm_param = parameters[1]
        osm_class_param = parameters[6]
        if osm_param.value and not osm_class_param.altered:
            try:
                fields = [f.name for f in arcpy.ListFields(osm_param.value)]
                if "fclass" in fields:
                    osm_class_param.value = "fclass"
            except Exception:
                pass

        return

    # ----------------------------------------------------------------
    def updateMessages(self, parameters):
        nha_param = parameters[0]
        osm_param = parameters[1]

        # Warn (not block) if inputs appear to be geographic - the actual
        # hard validation happens in execute() where we can also check
        # whether a projected_crs parameter has been supplied.
        for p in (nha_param, osm_param):
            if p.value:
                try:
                    desc = arcpy.Describe(p.value)
                    sr = desc.spatialReference
                    if sr is not None and sr.type == "Geographic":
                        proj_param = parameters[8]
                        if not proj_param.value:
                            p.setWarningMessage(
                                "Input has a geographic (unprojected) "
                                "coordinate system. Distance-based "
                                "matching requires a projected coordinate "
                                "system. Please supply the 'Projected "
                                "Coordinate System for Distance Matching' "
                                "parameter.")
                except Exception:
                    pass

        # If report generation is requested, a report folder is required.
        generate_report_param = parameters[9]
        report_folder_param = parameters[10]
        if generate_report_param.value and not report_folder_param.value:
            report_folder_param.setErrorMessage(
                "A Report Output Folder is required when 'Generate Final "
                "Statistical Summary Report (PDF)' is checked.")
        return

    # ----------------------------------------------------------------
    def execute(self, parameters, messages):

        try:
            # ---- Pull parameter values ----
            nha_input = parameters[0].valueAsText
            osm_input = parameters[1].valueAsText
            output_gdb = parameters[2].valueAsText
            tolerance_txt = parameters[3].valueAsText or "10 Meters"
            nha_name_field = parameters[4].valueAsText or "Name"
            nha_folder_field = parameters[5].valueAsText or "FolderPath"
            osm_class_field = parameters[6].valueAsText or "fclass"
            create_diagnostics = parameters[7].value
            if create_diagnostics is None:
                create_diagnostics = True
            projected_crs = parameters[8].value  # may be None
            generate_report = parameters[9].value
            if generate_report is None:
                generate_report = True
            report_folder = parameters[10].valueAsText  # may be None
            positional_tolerance_txt = parameters[11].valueAsText or "10 Meters"

            # ---- STEP 0: Validate ----
            validate_inputs(nha_input, osm_input, output_gdb,
                             nha_name_field, nha_folder_field,
                             osm_class_field, tolerance_txt)

            arcpy.AddMessage("=" * 70)
            arcpy.AddMessage("Road Features Classification - starting")
            arcpy.AddMessage("=" * 70)

            # Determine working spatial reference for distance-based ops.
            working_sr = determine_working_spatial_reference(
                nha_input, osm_input, projected_crs)

            # ---- Output dataset paths ----
            fc_nha_prepared = os.path.join(output_gdb, "X01_NHA_Prepared")
            fc_osm_prepared = os.path.join(output_gdb, "X02_OSM_Prepared")
            tbl_near = os.path.join(output_gdb, "X03_NHA_OSM_NearTable")
            fc_comparison = os.path.join(output_gdb, "X04_NHA_OSM_Comparison")
            fc_final = os.path.join(output_gdb, "X05_Final_Road_Classification")
            tbl_summary = os.path.join(output_gdb, "Classification_Summary")

            # ---- STEP 1: Prepare + classify NHA (never touches original) ----
            arcpy.AddMessage("Preparing NHA dataset...")
            prepare_nha(nha_input, fc_nha_prepared, working_sr)

            arcpy.AddMessage("Removing null/empty geometry rows...")
            remove_null_geometry(fc_nha_prepared, "NHA")

            arcpy.AddMessage("Classifying NHA roads...")
            classify_nha_featureclass(fc_nha_prepared, nha_name_field,
                                       nha_folder_field)

            # ---- STEP 2: Prepare + classify OSM (relevant subset only) ----
            arcpy.AddMessage("Preparing OSM dataset (relevant classes only, "
                              "for performance)...")
            prepare_osm(osm_input, fc_osm_prepared, osm_class_field,
                        working_sr, fc_nha_prepared, tolerance_txt)

            arcpy.AddMessage("Removing null/empty geometry rows...")
            remove_null_geometry(fc_osm_prepared, "OSM")

            arcpy.AddMessage("Classifying OSM roads...")
            classify_osm_featureclass(fc_osm_prepared, osm_class_field)

            # Detect optional OSM 'ref' / 'name' fields for route-code
            # (name/ref) supporting-evidence cross-matching. Neither is
            # required - if absent, name/ref confirmation is simply
            # skipped and matching falls back to class-only comparison.
            osm_fields_present = [f.name for f in arcpy.ListFields(fc_osm_prepared)]
            osm_ref_field = "ref" if "ref" in osm_fields_present else None
            osm_name_field = "name" if "name" in osm_fields_present else None
            if osm_ref_field is None and osm_name_field is None:
                arcpy.AddWarning("  Neither 'ref' nor 'name' field found on "
                                  "the OSM layer - route-code (name/ref) "
                                  "cross-matching will be skipped.")

            # ---- STEP 3: Spatial matching ----
            arcpy.AddMessage("Matching NHA and OSM roads (Generate Near "
                              "Table, tolerance = %s)..." % tolerance_txt)
            create_matches(fc_nha_prepared, fc_osm_prepared, tbl_near,
                            tolerance_txt)

            # ---- STEP 4: Compare classifications, build comparison FC ----
            arcpy.AddMessage("Calculating classification comparison "
                              "(class rules + name/ref supporting "
                              "evidence)...")
            match_info = compare_classifications(
                fc_nha_prepared, fc_osm_prepared, tbl_near,
                nha_name_field, osm_ref_field, osm_name_field)

            arcpy.AddMessage("Creating comparison output...")
            create_comparison_output(fc_nha_prepared, fc_osm_prepared,
                                      tbl_near, match_info, fc_comparison,
                                      nha_name_field, nha_folder_field)

            # ---- STEP 5: Final classification output ----
            arcpy.AddMessage("Creating final output (Motorway / National "
                              "Highway only)..." if RESTRICT_FINAL_OUTPUT_TO_SCOPE
                              else "Creating final output...")
            create_final_output(fc_nha_prepared, match_info, fc_final,
                                 nha_name_field, nha_folder_field)

            # ---- STEP 6: Summary table ----
            arcpy.AddMessage("Creating summary table...")
            create_summary(fc_final, tbl_summary)

            # ---- STEP 7: Diagnostic cleanup ----
            if not create_diagnostics:
                arcpy.AddMessage("Diagnostic outputs disabled - removing "
                                  "intermediate near table...")
                if arcpy.Exists(tbl_near):
                    arcpy.Delete_management(tbl_near)

            arcpy.AddMessage("=" * 70)
            arcpy.AddMessage("Classification and matching complete.")
            arcpy.AddMessage("Final output: %s" % fc_final)
            arcpy.AddMessage("Summary table: %s" % tbl_summary)
            arcpy.AddMessage("=" * 70)

            # ---- STEP 8-12: Final Statistical Summary Report (PDF) ----
            # Runs as a continuation of the same tool, in the same
            # execution, using the outputs just produced above. This is
            # deliberately part of ONE tool rather than a second tool, so
            # the whole pipeline - classification through to the final
            # statistical report - is always a single click.
            if generate_report:
                arcpy.AddMessage("=" * 70)
                arcpy.AddMessage("Generating Final Statistical Summary "
                                  "Report (NHA vs OSM)...")
                arcpy.AddMessage("=" * 70)

                stats = {}

                arcpy.AddMessage("[1/12] Dataset inventory and baseline "
                                  "statistics...")
                stats["inventory"] = compute_inventory_stats(
                    fc_nha_prepared, fc_osm_prepared)
                stats["review_detail"] = compute_review_detail(
                    fc_nha_prepared, nha_name_field)

                arcpy.AddMessage("[2/12] Name and attribute matching...")
                stats["name_match"] = compute_name_attribute_matching(fc_final)

                arcpy.AddMessage("[3/12] Geographic/spatial matching tiers...")
                stats["spatial_match"] = compute_spatial_matching_tiers(
                    fc_nha_prepared, fc_osm_prepared, fc_final, output_gdb)

                arcpy.AddMessage("[4/12] Geometric alignment assessment...")
                stats["alignment"] = compute_geometric_alignment(
                    fc_nha_prepared, fc_osm_prepared, fc_final, output_gdb)

                arcpy.AddMessage("[5/12] Perfect Match identification...")
                stats["perfect_match"] = compute_perfect_match(
                    fc_final, stats["alignment"]["per_feature"])

                arcpy.AddMessage("[6/12] Road classification agreement...")
                stats["class_agreement"] = compute_classification_agreement(fc_final)

                arcpy.AddMessage("[7/12] Mismatch and error taxonomy...")
                stats["mismatch"] = compute_mismatch_taxonomy(
                    fc_final, stats["name_match"], stats["alignment"])

                arcpy.AddMessage("[8/12] NHA network completeness in OSM...")
                stats["completeness"] = compute_network_completeness(fc_final)

                arcpy.AddMessage("[9/12] Length-based network comparison...")
                stats["length_comparison"] = compute_length_comparison(
                    fc_nha_prepared, fc_osm_prepared, fc_final)

                arcpy.AddMessage("[10/12] OSM fragmentation and "
                                  "representation...")
                stats["fragmentation"] = compute_fragmentation(fc_final)

                arcpy.AddMessage("[11/12] Spatial accuracy and positional "
                                  "deviation...")
                stats["positional"] = compute_positional_accuracy(
                    fc_nha_prepared, fc_osm_prepared, output_gdb,
                    positional_tolerance_txt)

                arcpy.AddMessage("[12/12] Overall classification and data "
                                  "quality assessment...")
                stats["overall"] = compute_overall_quality_assessment(stats)

                arcpy.AddMessage("Writing PDF report...")
                report_path = write_statistical_report_pdf(
                    stats, report_folder, output_gdb)

                arcpy.AddMessage("Writing supporting tables to "
                                  "geodatabase...")
                write_supporting_tables(stats, output_gdb)

                arcpy.AddMessage("Report: %s" % report_path)

            arcpy.AddMessage("=" * 70)
            arcpy.AddMessage("Process completed successfully.")
            arcpy.AddMessage("=" * 70)

        except arcpy.ExecuteError:
            arcpy.AddError("ArcPy geoprocessing error occurred:")
            arcpy.AddError(arcpy.GetMessages(2))
        except Exception as e:
            arcpy.AddError("An unexpected error occurred: %s" % str(e))
            arcpy.AddError(traceback.format_exc())

        return


# ==========================================================================
# SECTION C: HELPER FUNCTIONS
# ==========================================================================

def validate_inputs(nha_input, osm_input, output_gdb, nha_name_field,
                     nha_folder_field, osm_class_field, tolerance_txt):
    """
    Validates all required inputs before any processing begins.
    Raises a clear Exception (caught in execute()) rather than allowing an
    obscure ArcPy failure deep inside the workflow.
    """
    if not arcpy.Exists(nha_input):
        raise Exception("NHA input layer does not exist or is not "
                         "accessible: %s" % nha_input)
    if not arcpy.Exists(osm_input):
        raise Exception("OSM input layer does not exist or is not "
                         "accessible: %s" % osm_input)

    nha_desc = arcpy.Describe(nha_input)
    osm_desc = arcpy.Describe(osm_input)

    if nha_desc.shapeType != "Polyline":
        raise Exception("NHA input layer must be Polyline geometry. "
                         "Found: %s" % nha_desc.shapeType)
    if osm_desc.shapeType != "Polyline":
        raise Exception("OSM input layer must be Polyline geometry. "
                         "Found: %s" % osm_desc.shapeType)

    if not arcpy.Exists(output_gdb):
        raise Exception("Output Geodatabase does not exist: %s. Please "
                         "create it first in ArcCatalog (File Geodatabase)."
                         % output_gdb)

    out_desc = arcpy.Describe(output_gdb)
    if out_desc.dataType not in ("Workspace",):
        raise Exception("Output Geodatabase parameter does not point to a "
                         "valid workspace: %s" % output_gdb)

    nha_fields = [f.name for f in arcpy.ListFields(nha_input)]
    if nha_name_field not in nha_fields:
        raise Exception("NHA Name Field '%s' does not exist in the NHA "
                         "input layer. Available fields: %s"
                         % (nha_name_field, ", ".join(nha_fields)))
    if nha_folder_field not in nha_fields:
        raise Exception("NHA FolderPath Field '%s' does not exist in the "
                         "NHA input layer. Available fields: %s"
                         % (nha_folder_field, ", ".join(nha_fields)))

    osm_fields = [f.name for f in arcpy.ListFields(osm_input)]
    if osm_class_field not in osm_fields:
        raise Exception("OSM Classification Field '%s' does not exist in "
                         "the OSM input layer. Available fields: %s"
                         % (osm_class_field, ", ".join(osm_fields)))

    # Validate tolerance is a parseable linear unit, e.g. "10 Meters"
    try:
        parts = tolerance_txt.strip().split()
        float(parts[0])
        if len(parts) < 2:
            raise Exception()
    except Exception:
        raise Exception("Matching Tolerance is not a valid linear unit "
                         "(expected format like '10 Meters'). Got: %s"
                         % tolerance_txt)

    arcpy.AddMessage("Input validation passed.")
    return


def determine_working_spatial_reference(nha_input, osm_input, projected_crs):
    """
    Distance-based matching (Generate Near Table with a linear-unit
    tolerance) must not be performed in a geographic (lat/lon) coordinate
    system, since distances there are in degrees, not meters, and are
    non-uniform across latitude.

    Decision logic:
      - If the user supplied a projected_crs parameter, always use it
        (explicit user choice wins).
      - Else, if the NHA input is already in a projected CRS, use the NHA
        input's own CRS as the common working CRS (keeps geometry as close
        to source as possible).
      - Else, if the OSM input is already in a projected CRS, use that.
      - Else (both inputs are geographic and no projected_crs supplied),
        raise an explicit error. We deliberately do NOT guess a UTM zone
        automatically, because Pakistan spans UTM zones 41N, 42N and 43N,
        and silently picking one would distort distances for the others.
    """
    if projected_crs is not None:
        sr = projected_crs
        if sr.type != "Projected":
            raise Exception("The supplied 'Projected Coordinate System' "
                             "parameter is not a projected coordinate "
                             "system. Please choose a projected CRS "
                             "appropriate for Pakistan (e.g. a UTM zone).")
        arcpy.AddMessage("Using user-supplied projected coordinate system: "
                          "%s" % sr.name)
        return sr

    nha_sr = arcpy.Describe(nha_input).spatialReference
    osm_sr = arcpy.Describe(osm_input).spatialReference

    if nha_sr is not None and nha_sr.type == "Projected":
        arcpy.AddMessage("Using NHA input's projected coordinate system as "
                          "the working CRS: %s" % nha_sr.name)
        return nha_sr

    if osm_sr is not None and osm_sr.type == "Projected":
        arcpy.AddMessage("Using OSM input's projected coordinate system as "
                          "the working CRS: %s" % osm_sr.name)
        return osm_sr

    raise Exception(
        "Both NHA and OSM inputs are in a geographic (unprojected) "
        "coordinate system, and no 'Projected Coordinate System for "
        "Distance Matching' parameter was supplied. Distance-based "
        "matching cannot safely proceed without a projected CRS "
        "(Pakistan spans multiple UTM zones, so one cannot be guessed "
        "automatically). Please supply an appropriate projected "
        "coordinate system, e.g. WGS 1984 UTM Zone 42N or the Pakistan "
        "Standard Grid appropriate to your study area.")


def prepare_nha(nha_input, fc_nha_prepared, working_sr):
    """
    Copies the ORIGINAL NHA input into the output geodatabase as a new
    working feature class, projecting into working_sr if required.
    The original nha_input layer/feature class is never written to.
    Also adds all classification/QC fields needed downstream, all with
    safe existence checks so re-running the tool does not error out or
    duplicate fields.
    """
    out_workspace = os.path.dirname(fc_nha_prepared)
    out_name = os.path.basename(fc_nha_prepared)

    nha_desc = arcpy.Describe(nha_input)
    if nha_desc.spatialReference.factoryCode != working_sr.factoryCode:
        arcpy.AddMessage("  Projecting NHA working copy to match analysis "
                          "coordinate system...")
        arcpy.Project_management(nha_input, fc_nha_prepared, working_sr)
    else:
        arcpy.FeatureClassToFeatureClass_conversion(
            nha_input, out_workspace, out_name)

    # Add an OID-preservation field so downstream outputs can always trace
    # back to the ORIGINAL source NHA feature, even after further copies.
    add_field_if_missing(fc_nha_prepared, FLD_NHA_SRC_OID, "LONG")
    oid_field = arcpy.Describe(fc_nha_prepared).OIDFieldName
    with arcpy.da.UpdateCursor(fc_nha_prepared,
                                [oid_field, FLD_NHA_SRC_OID]) as cur:
        for row in cur:
            row[1] = row[0]
            cur.updateRow(row)

    # Add classification / QC fields used later in the workflow.
    add_field_if_missing(fc_nha_prepared, FLD_NHA_CLASS, "TEXT", length=30)
    add_field_if_missing(fc_nha_prepared, FLD_NHA_CATEGORY, "TEXT", length=50)
    add_field_if_missing(fc_nha_prepared, FLD_CPEC_FLAG, "TEXT", length=5)
    add_field_if_missing(fc_nha_prepared, FLD_QC_NOTE, "TEXT", length=255)

    count = int(arcpy.GetCount_management(fc_nha_prepared).getOutput(0))
    arcpy.AddMessage("  NHA working copy created with %d features." % count)
    return


def prepare_osm(osm_input, fc_osm_prepared, osm_class_field, working_sr,
                 fc_nha_prepared, tolerance_txt):
    """
    Prepares the OSM working copy WITHOUT looping through all ~299,043
    input features in Python. Two filters are applied server-side via
    ArcGIS geoprocessing (fast, uses attribute/spatial indexes):

      1. Attribute filter: only fclass values in OSM_RELEVANT_FCLASS are
         kept (see Section A.2 for rationale).
      2. Spatial filter: only OSM features within (tolerance + a safety
         buffer) of any NHA feature are kept, using
         Select Layer By Location, which uses the spatial index and does
         NOT iterate feature-by-feature in Python.

    This keeps the OSM working feature class small (typically a few
    thousand features for a national roads dataset) so that the
    subsequent Generate Near Table call is fast.
    """
    # Build a safe SQL WHERE clause for the fclass filter.
    delim_field = arcpy.AddFieldDelimiters(osm_input, osm_class_field)
    quoted_values = ", ".join(["'%s'" % v for v in OSM_RELEVANT_FCLASS])
    where_clause = "%s IN (%s)" % (delim_field, quoted_values)

    arcpy.AddMessage("  Applying OSM attribute filter (%s)..."
                      % ", ".join(OSM_RELEVANT_FCLASS))

    osm_layer = "osm_attr_lyr"
    if arcpy.Exists(osm_layer):
        arcpy.Delete_management(osm_layer)
    arcpy.MakeFeatureLayer_management(osm_input, osm_layer,
                                       where_clause=where_clause)

    attr_count = int(arcpy.GetCount_management(osm_layer).getOutput(0))
    arcpy.AddMessage("  %d OSM features match the relevant fclass filter."
                      % attr_count)

    if attr_count == 0:
        arcpy.AddWarning("  No OSM features matched the relevant fclass "
                          "filter. Matching step will find zero matches. "
                          "Check OSM_RELEVANT_FCLASS configuration and the "
                          "OSM Classification Field parameter.")

    # Spatial filter: keep only OSM features near any NHA feature.
    # Use a generous search distance (tolerance + fixed safety margin) so
    # we do not risk excluding legitimate matches at the tolerance edge
    # due to any rounding/unit conversion differences.
    tol_value, tol_unit = _parse_linear_unit(tolerance_txt)
    safety_distance_txt = "%s %s" % (str(tol_value * 3 + 50), tol_unit)

    arcpy.AddMessage("  Applying OSM spatial filter (within %s of any NHA "
                      "feature)..." % safety_distance_txt)
    arcpy.SelectLayerByLocation_management(
        osm_layer, "WITHIN_A_DISTANCE", fc_nha_prepared,
        search_distance=safety_distance_txt, selection_type="NEW_SELECTION")

    spatial_count = int(arcpy.GetCount_management(osm_layer).getOutput(0))
    arcpy.AddMessage("  %d OSM features remain after spatial filter."
                      % spatial_count)

    out_workspace = os.path.dirname(fc_osm_prepared)
    out_name = os.path.basename(fc_osm_prepared)

    osm_desc = arcpy.Describe(osm_input)
    if osm_desc.spatialReference.factoryCode != working_sr.factoryCode:
        arcpy.AddMessage("  Projecting OSM working copy to match analysis "
                          "coordinate system...")
        arcpy.Project_management(osm_layer, fc_osm_prepared, working_sr)
    else:
        arcpy.FeatureClassToFeatureClass_conversion(
            osm_layer, out_workspace, out_name)

    arcpy.Delete_management(osm_layer)

    # Preserve original OSM OID for traceability.
    add_field_if_missing(fc_osm_prepared, "OSM_Src_OID", "LONG")
    oid_field = arcpy.Describe(fc_osm_prepared).OIDFieldName
    with arcpy.da.UpdateCursor(fc_osm_prepared,
                                [oid_field, "OSM_Src_OID"]) as cur:
        for row in cur:
            row[1] = row[0]
            cur.updateRow(row)

    add_field_if_missing(fc_osm_prepared, FLD_OSM_CLASS, "TEXT", length=30)

    final_count = int(arcpy.GetCount_management(fc_osm_prepared).getOutput(0))
    arcpy.AddMessage("  OSM working copy created with %d features "
                      "(reduced from %s original)."
                      % (final_count,
                         arcpy.GetCount_management(osm_input).getOutput(0)))
    return


def remove_null_geometry(fc, label):
    """
    Deletes any row in fc whose geometry is null/empty (SHAPE@LENGTH is
    None or 0), or whose OID-preservation field could not be set. This
    directly answers the request to "remove null features" - it operates
    on the WORKING COPY only (fc_nha_prepared / fc_osm_prepared inside the
    output geodatabase), never on the original input layers, consistent
    with the "never modify original datasets" requirement.

    A null-geometry row usually comes from a corrupt or zero-length
    digitized feature in the source data; keeping it would make later
    distance/near calculations either fail or silently return meaningless
    results, so removing it up front is the correct place to handle it.
    """
    oid_field = arcpy.Describe(fc).OIDFieldName
    ids_to_delete = []
    with arcpy.da.SearchCursor(fc, [oid_field, "SHAPE@LENGTH"]) as cur:
        for row in cur:
            oid_val, length_val = row
            if length_val is None or length_val <= 0:
                ids_to_delete.append(oid_val)

    if not ids_to_delete:
        arcpy.AddMessage("  No null/empty-geometry %s features found." % label)
        return

    delim_field = arcpy.AddFieldDelimiters(fc, oid_field)
    id_list_str = ", ".join([str(i) for i in ids_to_delete])
    where_clause = "%s IN (%s)" % (delim_field, id_list_str)

    lyr_name = "null_cleanup_lyr"
    if arcpy.Exists(lyr_name):
        arcpy.Delete_management(lyr_name)
    arcpy.MakeFeatureLayer_management(fc, lyr_name, where_clause=where_clause)
    arcpy.DeleteFeatures_management(lyr_name)
    arcpy.Delete_management(lyr_name)

    arcpy.AddWarning("  Removed %d null/empty-geometry %s feature(s) from "
                      "the working copy (%s)." % (len(ids_to_delete), label, fc))
    return


def add_field_if_missing(fc, field_name, field_type, length=None):
    """
    Adds a field to fc only if it does not already exist, so the tool can
    be re-run repeatedly without errors or duplicate fields. Never touches
    or renames any existing field (field-name safety requirement).
    """
    existing = [f.name for f in arcpy.ListFields(fc)]
    if field_name in existing:
        return
    if length is not None:
        arcpy.AddField_management(fc, field_name, field_type,
                                   field_length=length)
    else:
        arcpy.AddField_management(fc, field_name, field_type)
    return


def _parse_linear_unit(tolerance_txt):
    """
    Parses a string like '10 Meters' into (10.0, 'Meters').
    """
    parts = tolerance_txt.strip().split()
    value = float(parts[0])
    unit = " ".join(parts[1:]) if len(parts) > 1 else "Meters"
    return value, unit


# ==========================================================================
# SECTION D: NHA CLASSIFICATION
# ==========================================================================

def classify_nha(name_value, folderpath_value, oid_value):
    """
    Determines (NHA_Class, NHA_Category, CPEC_Flag, QC_Note) for a single
    NHA feature, given its Name, FolderPath and OID.

    RULES (in priority order - see Section A.1 for the editable config):
      1. Manual override (by OID, then by exact Name) - always wins.
      2. Named-route rules (substring match against NHA_NAMED_ROUTE_RULES).
      3. Route-code prefix regex against Name:
           M-<digits>  -> Motorway
           N-<digits>  -> National Highway
           S-<digits>  -> Strategic (explicitly NOT National Highway)
      4. If nothing matches -> NHA_Class = 'Review', QC_Note explains why.
         We do NOT fall back to FolderPath alone to decide NHA_Class,
         per the explicit instruction that FolderPath should not
         determine classification by itself. FolderPath is used ONLY to
         set CPEC_Flag.

    Returns a 4-tuple of strings.
    """
    name_value = (name_value or "").strip()
    folderpath_value = (folderpath_value or "")

    # CPEC_Flag is independent of the class decision below.
    cpec_flag = "Yes" if CPEC_FOLDER_KEYWORD.lower() in folderpath_value.lower() else "No"

    qc_note = ""

    # --- 1. Manual overrides (by OID, then by Name) ---
    if oid_value in NHA_MANUAL_OVERRIDES:
        cls, category = NHA_MANUAL_OVERRIDES[oid_value]
        return cls, category, cpec_flag, "Manual override applied (by OID)."
    if name_value in NHA_MANUAL_OVERRIDES:
        cls, category = NHA_MANUAL_OVERRIDES[name_value]
        return cls, category, cpec_flag, "Manual override applied (by Name)."

    # --- 2. Named-route rules ---
    for substring, cls, category in NHA_NAMED_ROUTE_RULES:
        if substring.lower() in name_value.lower():
            return cls, category, cpec_flag, ""

    # --- 3. Route-code prefix rules ---
    if NHA_MOTORWAY_PATTERN.match(name_value):
        return "Motorway", "Motorway (M-series)", cpec_flag, ""

    if NHA_NATIONAL_HIGHWAY_PATTERN.match(name_value):
        return "National Highway", "National Highway (N-series)", cpec_flag, ""

    if NHA_STRATEGIC_PATTERN.match(name_value):
        return ("Strategic", "Strategic Road (S-series)", cpec_flag,
                "Classified as Strategic, not National Highway, per "
                "explicit rule - review if this is unexpected.")

    # --- 4. No rule matched: flag for review rather than guessing ---
    qc_note = ("No classification rule matched Name='%s'. Flagged for "
               "manual review. Add a rule to NHA_NAMED_ROUTE_RULES or "
               "NHA_MANUAL_OVERRIDES if this should be classified "
               "automatically." % name_value)
    return "Review", "Unclassified - Needs Review", cpec_flag, qc_note


def classify_nha_featureclass(fc_nha_prepared, nha_name_field,
                               nha_folder_field):
    """
    Applies classify_nha() to every row of the NHA working feature class
    using an UpdateCursor (fast for ~121 features; this is explicitly NOT
    the performance-sensitive part of the workflow, unlike OSM handling).
    """
    fields = [FLD_NHA_SRC_OID, nha_name_field, nha_folder_field,
              FLD_NHA_CLASS, FLD_NHA_CATEGORY, FLD_CPEC_FLAG, FLD_QC_NOTE]

    counts = {}
    review_count = 0

    with arcpy.da.UpdateCursor(fc_nha_prepared, fields) as cursor:
        for row in cursor:
            oid_val, name_val, folder_val = row[0], row[1], row[2]
            cls, category, cpec_flag, qc_note = classify_nha(
                name_val, folder_val, oid_val)

            row[3] = cls
            row[4] = category
            row[5] = cpec_flag
            row[6] = qc_note
            cursor.updateRow(row)

            counts[cls] = counts.get(cls, 0) + 1
            if cls == "Review":
                review_count += 1

    for cls_name, cnt in counts.items():
        arcpy.AddMessage("  NHA_Class '%s': %d features" % (cls_name, cnt))

    if review_count > 0:
        arcpy.AddWarning("  %d NHA feature(s) flagged as 'Review' - no "
                          "classification rule matched. Check QC_Note "
                          "field in %s." % (review_count, fc_nha_prepared))
    return


# ==========================================================================
# SECTION E: OSM CLASSIFICATION
# ==========================================================================

def classify_osm_featureclass(fc_osm_prepared, osm_class_field):
    """
    Populates Road_Class on the OSM working feature class using the
    explicit OSM_CLASS_MAPPING dictionary (Section A.2). Any fclass value
    not present in the mapping is set to 'Other' and reported via
    AddWarning, so unexpected values are never silently dropped.
    """
    fields = [osm_class_field, FLD_OSM_CLASS]
    counts = {}
    unmapped_values = set()

    with arcpy.da.UpdateCursor(fc_osm_prepared, fields) as cursor:
        for row in cursor:
            fclass_val = (row[0] or "").strip().lower()
            road_class = OSM_CLASS_MAPPING.get(fclass_val)
            if road_class is None:
                road_class = "Other"
                if fclass_val:
                    unmapped_values.add(fclass_val)
            row[1] = road_class
            cursor.updateRow(row)
            counts[road_class] = counts.get(road_class, 0) + 1

    for cls_name, cnt in counts.items():
        arcpy.AddMessage("  Road_Class '%s': %d features" % (cls_name, cnt))

    if unmapped_values:
        arcpy.AddWarning(
            "  The following OSM fclass values were NOT found in "
            "OSM_CLASS_MAPPING and were set to 'Other': %s. Add them to "
            "OSM_CLASS_MAPPING in the toolbox code if they should be "
            "classified differently." % ", ".join(sorted(unmapped_values)))
    return


# ==========================================================================
# SECTION F: SPATIAL MATCHING
# ==========================================================================

def create_matches(fc_nha_prepared, fc_osm_prepared, tbl_near, tolerance_txt):
    """
    Performs the core spatial matching using arcpy.GenerateNearTable_analysis.

    WHY Generate Near Table (rather than Spatial Join or Intersect):
      - closest='ALL' returns every OSM feature within the tolerance of
        each NHA feature (not just the single nearest one), which is
        required to support legitimate Match_Count > 1 cases (section
        15.D).
      - It works directly on line-to-line geometry, computing true
        minimum distance between the two lines, which is more appropriate
        for "proximity/corridor" matching than a single-point Spatial
        Join, and does not require exact geometric overlap (unlike
        Intersect, which would miss parallel/offset digitizing of the
        same physical road - a common issue between an authoritative
        survey dataset and a crowd-sourced dataset like OSM).
      - It does not require or use line direction, satisfying the
        requirement that "road direction should NOT be required to
        match".
      - It uses the coordinate system's spatial index internally and
        operates on the (already filtered, small) working feature
        classes, so it does not loop through the original 299,043 OSM
        features.

    The output near table contains one row per (NHA feature, nearby OSM
    feature) pair within tolerance - this is intentionally a many-to-many
    table; aggregation to one-row-per-NHA-feature happens later in
    compare_classifications().
    """
    arcpy.GenerateNearTable_analysis(
        in_features=fc_nha_prepared,
        near_features=fc_osm_prepared,
        out_table=tbl_near,
        search_radius=tolerance_txt,
        location="NO_LOCATION",
        angle="NO_ANGLE",
        closest="ALL",           # return all candidates within tolerance
        closest_count=0,          # 0 = unlimited
        method="PLANAR")          # valid because working_sr is projected

    near_count = int(arcpy.GetCount_management(tbl_near).getOutput(0))
    arcpy.AddMessage("  Near table generated: %d candidate NHA-OSM pairs "
                      "within tolerance." % near_count)
    return


# ==========================================================================
# SECTION G: CLASSIFICATION COMPARISON
# ==========================================================================

def compare_classifications(fc_nha_prepared, fc_osm_prepared, tbl_near,
                             nha_name_field, osm_ref_field, osm_name_field):
    """
    Aggregates the many-to-many near table into per-NHA-feature match
    information, and determines Match_Status per NHA feature.

    Returns a dict keyed by NHA OID (the OID field of fc_nha_prepared),
    with values:
        {
          'nha_class': str,
          'match_count': int,
          'match_status': str,        # Matched / Matched (Name Confirmed) /
                                       # Conflict / Multiple / Unmatched /
                                       # SevereMismatch
          'osm_match_ids': [list of OSM Src OIDs, may be empty],
          'osm_classes': [list of OSM Road_Class values, may be empty],
          'best_osm_id': int or None,
          'best_osm_class': str or None,
          'qc_note': str
        }

    MATCH_STATUS DEFINITIONS (explicit, see also Section A.3):
        Unmatched  - zero OSM features found within tolerance.
        Matched    - exactly one OSM match, and its Road_Class agrees
                     with NHA_Class per NHA_OSM_AGREEMENT.
        Multiple   - more than one OSM match, and at least one of them
                     agrees with NHA_Class. (Match_Count > 1 is NOT
                     itself an error per spec section 15.D.)
        Conflict   - one or more OSM matches exist, none agree with
                     NHA_Class by class, AND no route-code (name/ref)
                     confirmation was found either.
        Matched (Name Confirmed) - one or more OSM matches exist; none
                     agree with NHA_Class by Road_Class alone, BUT at
                     least one matched OSM feature's route code (from
                     'ref' or 'name') exactly equals the NHA feature's
                     route code (e.g. NHA 'M-2 (...)' spatially matched
                     an OSM segment tagged ref='M2'). This is the
                     "combine both layers' names" cross-check requested:
                     name/ref is used ONLY as supporting evidence to
                     resolve a class-based conflict, never as the sole
                     matching criterion (the spatial match already
                     existed; the name only confirms which side is
                     right when classes disagree).
        SevereMismatch - subset of Conflict (no class agreement AND no
                     name confirmation) where the matched OSM_Class is in
                     NHA_OSM_SEVERE_MISMATCH (e.g. NHA=Motorway matched
                     only to OSM=Residential) - flagged more prominently
                     as a likely OSM data error.
    """
    # Build OID -> (NHA_Class, route_code, raw Name) lookup (small table,
    # ~121 rows). The raw Name is kept (not just the extracted route
    # code) so Road_Name can be built from it later.
    nha_oid_field = arcpy.Describe(fc_nha_prepared).OIDFieldName
    nha_class_lookup = {}
    nha_route_lookup = {}
    nha_name_raw_lookup = {}
    with arcpy.da.SearchCursor(
            fc_nha_prepared,
            [nha_oid_field, FLD_NHA_CLASS, nha_name_field]) as cur:
        for row in cur:
            nha_class_lookup[row[0]] = row[1]
            nha_route_lookup[row[0]] = extract_route_code(row[2])
            nha_name_raw_lookup[row[0]] = row[2]

    # Build OSM OID -> (Road_Class, route_code, raw ref/name) lookup. The
    # route code is tried first against 'ref' (OSM's dedicated
    # route-number field, e.g. 'N5', 'M2') and falls back to 'name' if
    # 'ref' has no route-code pattern, since some OSM segments only
    # carry the code in 'name'. The raw ref/name strings are kept
    # separately (osm_ref_raw_lookup / osm_name_raw_lookup) so Road_Name
    # can display OSM's own wording, not just the normalised code.
    osm_oid_field = arcpy.Describe(fc_osm_prepared).OIDFieldName
    osm_class_lookup = {}
    osm_route_lookup = {}
    osm_ref_raw_lookup = {}
    osm_name_raw_lookup = {}
    osm_read_fields = [osm_oid_field, FLD_OSM_CLASS]
    has_ref = osm_ref_field is not None
    has_name = osm_name_field is not None
    if has_ref:
        osm_read_fields.append(osm_ref_field)
    if has_name:
        osm_read_fields.append(osm_name_field)

    with arcpy.da.SearchCursor(fc_osm_prepared, osm_read_fields) as cur:
        for row in cur:
            oid_val = row[0]
            osm_class_lookup[oid_val] = row[1]
            idx = 2
            ref_val, name_val = None, None
            if has_ref:
                ref_val = row[idx]
                idx += 1
            if has_name:
                name_val = row[idx]
            osm_ref_raw_lookup[oid_val] = ref_val
            osm_name_raw_lookup[oid_val] = name_val
            route_code = extract_route_code(ref_val) if has_ref else None
            if route_code is None and has_name:
                route_code = extract_route_code(name_val)
            osm_route_lookup[oid_val] = route_code

    def _best_osm_display_name(osm_id):
        """Prefers OSM 'name' (more descriptive, e.g. 'M-2 Motorway')
        over 'ref' (bare code, e.g. 'M2') for the human-readable
        Road_Name - the reverse priority from route-code EXTRACTION
        above, which prefers 'ref' because it is the more reliable
        field for an exact code match."""
        if osm_id is None:
            return None
        return (_clean_display_name(osm_name_raw_lookup.get(osm_id)) or
                _clean_display_name(osm_ref_raw_lookup.get(osm_id)))

    # Read the near table (IN_FID -> NHA OID, NEAR_FID -> OSM OID).
    # Aggregate per NHA OID using a plain dict - bounded by the number of
    # near-table rows, not by the original 299,043 OSM feature count.
    matches_per_nha = {}
    with arcpy.da.SearchCursor(tbl_near, ["IN_FID", "NEAR_FID"]) as cur:
        for row in cur:
            in_fid, near_fid = row[0], row[1]
            matches_per_nha.setdefault(in_fid, []).append(near_fid)

    result = {}
    for nha_oid, nha_class in nha_class_lookup.items():
        osm_fids = matches_per_nha.get(nha_oid, [])
        osm_classes = [osm_class_lookup.get(fid, "Unknown")
                        for fid in osm_fids]
        nha_route = nha_route_lookup.get(nha_oid)

        match_count = len(osm_fids)
        agree_classes = NHA_OSM_AGREEMENT.get(nha_class, [])

        agreeing_pairs = [(fid, cls) for fid, cls in zip(osm_fids, osm_classes)
                           if cls in agree_classes]

        # Route-code (name/ref) supporting evidence: does any spatially
        # matched OSM feature carry the SAME route code as this NHA
        # feature? Only meaningful, and only ever consulted, when there
        # is at least one spatial match to begin with.
        name_confirmed_pairs = []
        if nha_route is not None:
            for fid, cls in zip(osm_fids, osm_classes):
                if osm_route_lookup.get(fid) == nha_route:
                    name_confirmed_pairs.append((fid, cls))

        qc_note = ""

        if match_count == 0:
            status = "Unmatched"
            best_osm_id, best_osm_class = None, None

        elif len(agreeing_pairs) > 0:
            # At least one matched OSM feature agrees with NHA_Class by
            # road class alone - the normal, expected case.
            best_osm_id, best_osm_class = agreeing_pairs[0]
            status = "Matched" if match_count == 1 else "Multiple"

        elif len(name_confirmed_pairs) > 0:
            # Classes disagreed, but the route code (e.g. 'M-2' / 'M2')
            # matches exactly - treat this as confirmed by name/ref
            # supporting evidence rather than a silent conflict. NHA_Class
            # is still what gets reported (OSM never overrides NHA), this
            # only changes Match_Status from Conflict to a confirmed state.
            best_osm_id, best_osm_class = name_confirmed_pairs[0]
            status = "Matched (Name Confirmed)"
            qc_note = ("OSM Road_Class ('%s') did not match NHA_Class "
                       "('%s') by class rules, but route code '%s' "
                       "matched exactly between NHA Name and OSM ref/name "
                       "- treated as confirmed via name/ref supporting "
                       "evidence." % (best_osm_class, nha_class, nha_route))

        else:
            # One or more matches exist, none agree by class, and no
            # route-code confirmation either -> genuine Conflict.
            best_osm_id, best_osm_class = osm_fids[0], osm_classes[0]
            severe = any(c in NHA_OSM_SEVERE_MISMATCH for c in osm_classes)
            status = "SevereMismatch" if severe else "Conflict"
            qc_note = ("NHA_Class='%s' did not agree with any matched OSM "
                       "Road_Class within tolerance (found: %s), and no "
                       "route-code confirmation was found. Flagged for "
                       "manual review; NHA classification retained as "
                       "authoritative." % (nha_class,
                                           ", ".join(sorted(set(osm_classes)))))

        best_osm_route = osm_route_lookup.get(best_osm_id) if best_osm_id is not None else None
        osm_display_name = _best_osm_display_name(best_osm_id)
        road_name = build_road_name(
            nha_name_raw_lookup.get(nha_oid), nha_route, osm_display_name,
            best_osm_route)

        result[nha_oid] = {
            "nha_class": nha_class,
            "match_count": match_count,
            "match_status": status,
            "osm_match_ids": osm_fids,
            "osm_classes": osm_classes,
            "best_osm_id": best_osm_id,
            "best_osm_class": best_osm_class,
            "qc_note": qc_note,
            "road_name": road_name,
            "nha_route_code": nha_route,
            "osm_route_code": best_osm_route,
            "osm_display_name": osm_display_name,
        }

    # Summary logging
    status_counts = {}
    for info in result.values():
        status_counts[info["match_status"]] = \
            status_counts.get(info["match_status"], 0) + 1
    for status_name, cnt in status_counts.items():
        arcpy.AddMessage("  Match_Status '%s': %d NHA features"
                          % (status_name, cnt))

    return result


# ==========================================================================
# SECTION H: OUTPUT GENERATION
# ==========================================================================

def determine_final_class(nha_class, match_status):
    """
    Implements the Final_Class decision table documented in Section A.4.

    NHA classification is authoritative. OSM never overrides it. OSM
    (via match_status) can only ever push a feature toward 'Review' when
    NHA itself was already ambiguous - it cannot demote a Motorway/
    National Highway to 'Other', and it cannot promote a Strategic/Other
    road to Motorway/National Highway.
    """
    if nha_class == "Review":
        return "Review"

    if nha_class in ("Motorway", "National Highway"):
        # NHA classification is kept regardless of match_status.
        # match_status is preserved separately as a QC signal - it does
        # NOT change Final_Class. This directly implements the
        # requirement that OSM must not silently override NHA.
        return nha_class

    # Strategic, or any other/unrecognised NHA_Class value.
    return "Other"


def create_comparison_output(fc_nha_prepared, fc_osm_prepared, tbl_near,
                              match_info, fc_comparison, nha_name_field,
                              nha_folder_field):
    """
    Creates 04_NHA_OSM_Comparison: one row per NHA feature carrying full
    traceability information, i.e. a human-readable version of the near
    table with classification comparison already applied. NHA features
    with zero matches still get exactly one row (with null OSM fields),
    so unmatched roads remain visible (per section 11: "Do not discard
    unmatched features").

    NOTE ON SCHEMA (fixed after initial review): this output is now built
    with an EXPLICIT field list rather than template=fc_nha_prepared. The
    previous version copied the NHA schema (including Name, FolderPath,
    and several KML-conversion artifact fields such as SymbolID, AltMode,
    Clamped, Extruded, Snippet, PopupInfo) but the insert cursor never
    actually wrote values into most of those fields, leaving them <Null>
    for every row. Building the schema explicitly guarantees every field
    that is created is also populated, and drops the irrelevant
    KML-artifact fields entirely.

    Geometry: copies the NHA line geometry (the authoritative geometry)
    so this output can be symbolised/mapped directly in ArcMap.
    """
    sr = arcpy.Describe(fc_nha_prepared).spatialReference
    arcpy.CreateFeatureclass_management(
        os.path.dirname(fc_comparison), os.path.basename(fc_comparison),
        "POLYLINE", spatial_reference=sr)

    arcpy.AddField_management(fc_comparison, "NHA_Name", "TEXT", field_length=150)
    arcpy.AddField_management(fc_comparison, "NHA_FolderPath", "TEXT", field_length=255)
    arcpy.AddField_management(fc_comparison, FLD_NHA_CLASS, "TEXT", field_length=30)
    arcpy.AddField_management(fc_comparison, FLD_NHA_CATEGORY, "TEXT", field_length=50)
    arcpy.AddField_management(fc_comparison, FLD_CPEC_FLAG, "TEXT", field_length=5)
    arcpy.AddField_management(fc_comparison, FLD_MATCH_COUNT, "LONG")
    arcpy.AddField_management(fc_comparison, FLD_MATCH_STATUS, "TEXT", field_length=30)
    arcpy.AddField_management(fc_comparison, FLD_OSM_MATCH_ID, "LONG")
    arcpy.AddField_management(fc_comparison, FLD_OSM_MATCH_CLASS, "TEXT", field_length=30)
    arcpy.AddField_management(fc_comparison, FLD_QC_NOTE, "TEXT", field_length=255)

    nha_oid_field = arcpy.Describe(fc_nha_prepared).OIDFieldName
    read_fields = [nha_oid_field, "SHAPE@", nha_name_field, nha_folder_field,
                   FLD_NHA_CLASS, FLD_NHA_CATEGORY, FLD_CPEC_FLAG]
    write_fields = ["SHAPE@", "NHA_Name", "NHA_FolderPath", FLD_NHA_CLASS,
                     FLD_NHA_CATEGORY, FLD_CPEC_FLAG, FLD_MATCH_COUNT,
                     FLD_MATCH_STATUS, FLD_OSM_MATCH_ID, FLD_OSM_MATCH_CLASS,
                     FLD_QC_NOTE]

    with arcpy.da.SearchCursor(fc_nha_prepared, read_fields) as search_cur, \
         arcpy.da.InsertCursor(fc_comparison, write_fields) as insert_cur:
        for row in search_cur:
            nha_oid, shape, name_val, folder_val, nha_class, nha_category, \
                cpec_flag = row
            info = match_info.get(nha_oid)
            if info is None:
                continue
            insert_cur.insertRow((
                shape, name_val, folder_val, nha_class, nha_category,
                cpec_flag, info["match_count"], info["match_status"],
                info["best_osm_id"], info["best_osm_class"],
                info["qc_note"]))

    count = int(arcpy.GetCount_management(fc_comparison).getOutput(0))
    arcpy.AddMessage("  Comparison output created with %d rows." % count)
    return


def create_final_output(fc_nha_prepared, match_info, fc_final,
                         nha_name_field, nha_folder_field):
    """
    Creates 05_Final_Road_Classification: the primary deliverable. One
    row per NHA feature (never duplicated, unlike the comparison output),
    carrying NHA info, NHA classification, best-matched OSM info, match
    status/count, and the Final_Class decision - fully traceable per
    Section "Workflow Traceability" in the module docstring.

    SCOPE FILTER: if RESTRICT_FINAL_OUTPUT_TO_SCOPE is True (default),
    only NHA features whose NHA_Class is in FINAL_OUTPUT_CLASSES (i.e.
    Motorway / National Highway) are written here. Strategic roads and
    unresolved 'Review' features are skipped in THIS output only - they
    remain fully visible and unmodified in X01_NHA_Prepared and
    X04_NHA_OSM_Comparison, so nothing is silently lost from the project,
    it is simply kept out of the final Motorway/National-Highway-only
    deliverable per the requested scope.

    SCHEMA NOTE: built with an explicit field list (see
    create_comparison_output docstring for why template= was dropped),
    fixing the previous version's <Null> Name/FolderPath bug.

    Road_Name / Road_Type (added per project requirement to name every
    road in the final classification layer): Road_Type mirrors
    Final_Class (Motorway / National Highway) under the plain field name
    the deliverable calls for. Road_Name is built by build_road_name()
    from the NHA reference name plus the matched OSM feature's name/ref
    - e.g. NHA 'N-85' matched to an OSM segment tagged ref='M-2' becomes
    'N-85 (OSM: M-2)', so a naming discrepancy between the two datasets
    is visible directly in the final layer's attribute table.
    """
    sr = arcpy.Describe(fc_nha_prepared).spatialReference
    arcpy.CreateFeatureclass_management(
        os.path.dirname(fc_final), os.path.basename(fc_final),
        "POLYLINE", spatial_reference=sr)

    arcpy.AddField_management(fc_final, "NHA_Name", "TEXT", field_length=150)
    arcpy.AddField_management(fc_final, "NHA_FolderPath", "TEXT", field_length=255)
    arcpy.AddField_management(fc_final, FLD_NHA_CLASS, "TEXT", field_length=30)
    arcpy.AddField_management(fc_final, FLD_NHA_CATEGORY, "TEXT", field_length=50)
    arcpy.AddField_management(fc_final, FLD_CPEC_FLAG, "TEXT", field_length=5)
    arcpy.AddField_management(fc_final, FLD_NHA_SRC_OID, "LONG")
    arcpy.AddField_management(fc_final, FLD_MATCH_COUNT, "LONG")
    arcpy.AddField_management(fc_final, FLD_MATCH_STATUS, "TEXT", field_length=30)
    arcpy.AddField_management(fc_final, FLD_OSM_MATCH_ID, "LONG")
    arcpy.AddField_management(fc_final, FLD_OSM_MATCH_CLASS, "TEXT", field_length=30)
    arcpy.AddField_management(fc_final, FLD_FINAL_CLASS, "TEXT", field_length=30)
    arcpy.AddField_management(fc_final, FLD_ROAD_TYPE, "TEXT", field_length=30)
    arcpy.AddField_management(fc_final, FLD_ROAD_NAME, "TEXT", field_length=300)
    arcpy.AddField_management(fc_final, FLD_QC_NOTE, "TEXT", field_length=255)

    nha_oid_field = arcpy.Describe(fc_nha_prepared).OIDFieldName
    read_fields = [nha_oid_field, "SHAPE@", nha_name_field, nha_folder_field,
                   FLD_NHA_CLASS, FLD_NHA_CATEGORY, FLD_CPEC_FLAG,
                   FLD_NHA_SRC_OID]
    write_fields = ["SHAPE@", "NHA_Name", "NHA_FolderPath", FLD_NHA_CLASS,
                     FLD_NHA_CATEGORY, FLD_CPEC_FLAG, FLD_NHA_SRC_OID,
                     FLD_MATCH_COUNT, FLD_MATCH_STATUS, FLD_OSM_MATCH_ID,
                     FLD_OSM_MATCH_CLASS, FLD_FINAL_CLASS, FLD_ROAD_TYPE,
                     FLD_ROAD_NAME, FLD_QC_NOTE]

    final_counts = {}
    skipped_out_of_scope = 0
    with arcpy.da.SearchCursor(fc_nha_prepared, read_fields) as search_cur, \
         arcpy.da.InsertCursor(fc_final, write_fields) as insert_cur:
        for row in search_cur:
            nha_oid, shape, name_val, folder_val, nha_class, nha_category, \
                cpec_flag, src_oid = row
            info = match_info.get(nha_oid)
            if info is None:
                continue

            final_class = determine_final_class(nha_class,
                                                  info["match_status"])

            if RESTRICT_FINAL_OUTPUT_TO_SCOPE and \
                    final_class not in FINAL_OUTPUT_CLASSES:
                skipped_out_of_scope += 1
                continue

            final_counts[final_class] = final_counts.get(final_class, 0) + 1

            qc_note = info["qc_note"]
            if info["match_status"] == "Unmatched" and nha_class in (
                    "Motorway", "National Highway"):
                qc_note = (qc_note + " " if qc_note else "") + \
                    "No corresponding OSM feature found within tolerance."

            insert_cur.insertRow((
                shape, name_val, folder_val, nha_class, nha_category,
                cpec_flag, src_oid, info["match_count"],
                info["match_status"], info["best_osm_id"],
                info["best_osm_class"], final_class, final_class,
                info["road_name"], qc_note))

    count = int(arcpy.GetCount_management(fc_final).getOutput(0))
    arcpy.AddMessage("  Final output created with %d rows." % count)
    for cls_name, cnt in final_counts.items():
        arcpy.AddMessage("    Final_Class '%s': %d" % (cls_name, cnt))
    if skipped_out_of_scope > 0:
        arcpy.AddMessage("  %d feature(s) excluded from final output as "
                          "out of scope (Strategic/Review/Other) - still "
                          "visible in X01_NHA_Prepared and "
                          "X04_NHA_OSM_Comparison."
                          % skipped_out_of_scope)
    return


def create_summary(fc_final, tbl_summary):
    """
    Creates the Classification_Summary diagnostic table: actual calculated
    counts grouped by (NHA_Class, OSM_Class, Match_Status), matching the
    format illustrated in section 14 of the specification. Built with a
    SearchCursor + dict aggregation (fast - bounded by the small number of
    NHA features, ~121 in the current dataset) and written out with an
    InsertCursor, so it works identically on ArcMap 10.8 without relying
    on any Pro-only summary/pivot tooling.

    NOTE: this reads from fc_final (X05_Final_Road_Classification), so if
    RESTRICT_FINAL_OUTPUT_TO_SCOPE is True (default), this summary only
    covers Motorway / National Highway features, per project scope -
    Strategic/Review counts are visible instead by querying
    X04_NHA_OSM_Comparison directly if ever needed.
    """
    if arcpy.Exists(tbl_summary):
        arcpy.Delete_management(tbl_summary)

    arcpy.CreateTable_management(os.path.dirname(tbl_summary),
                                  os.path.basename(tbl_summary))
    arcpy.AddField_management(tbl_summary, "NHA_Class", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_summary, "OSM_Class", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_summary, "Match_Status", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_summary, "Count", "LONG")

    read_fields = [FLD_NHA_CLASS, FLD_OSM_MATCH_CLASS, FLD_MATCH_STATUS]
    tally = {}
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for row in cur:
            nha_class, osm_class, match_status = row
            osm_class_key = osm_class if osm_class else "None"
            key = (nha_class, osm_class_key, match_status)
            tally[key] = tally.get(key, 0) + 1

    with arcpy.da.InsertCursor(
            tbl_summary, ["NHA_Class", "OSM_Class", "Match_Status", "Count"]) as cur:
        for (nha_class, osm_class_key, match_status), cnt in tally.items():
            cur.insertRow((nha_class, osm_class_key, match_status, cnt))

    row_count = int(arcpy.GetCount_management(tbl_summary).getOutput(0))
    arcpy.AddMessage("  Classification_Summary created with %d summary rows."
                      % row_count)
    return


# ==========================================================================
# SECTION I: STATISTICAL SUMMARY REPORT - NHA vs OSM
# ==========================================================================
#
# All functions in this section are READ-ONLY with respect to
# X01_NHA_Prepared, X02_OSM_Prepared and X05_Final_Road_Classification.
# They compute the thirteen report sections requested, each returning a
# plain dict of primitives (ints/floats/strings/lists) so the results can
# be written out to both a human-readable text report and a set of
# auditable geodatabase tables without re-deriving anything twice.
#
# UNITS: all lengths are read via SHAPE@LENGTH, which returns length in
# the feature class's stored linear unit (meters, since Tool 1 always
# projects working copies into a projected coordinate system - see
# determine_working_spatial_reference()). All lengths in this report are
# therefore in meters unless explicitly converted to kilometers for
# readability.

def _sr_linear_unit_name(fc):
    """Returns the linear unit name of fc's spatial reference (for
    labeling report output honestly rather than assuming meters)."""
    sr = arcpy.Describe(fc).spatialReference
    try:
        return sr.linearUnitName
    except Exception:
        return "unknown units"


# --------------------------------------------------------------------
# 1. Dataset Inventory and Baseline Statistics
# --------------------------------------------------------------------

def compute_inventory_stats(fc_nha, fc_osm):
    """
    Requirement 1: total NHA and OSM feature counts, plus separate
    counts and total lengths for Motorway and National Highway.

    NHA counts/lengths are read directly from X01_NHA_Prepared
    (NHA_Class field). OSM counts/lengths are read from X02_OSM_Prepared
    (Road_Class field) - note this is the OSM working copy already
    filtered to OSM_RELEVANT_FCLASS by Tool 1, i.e. it represents "OSM
    features considered as candidates for Motorway/National Highway
    matching", not the full 299,043-feature original OSM dataset. This
    is stated explicitly in the report so the baseline is never
    misread as "all OSM roads in Pakistan".
    """
    unit_name = _sr_linear_unit_name(fc_nha)

    nha_total_count = 0
    nha_total_length = 0.0
    nha_by_class = {}  # class -> {'count': int, 'length': float}

    with arcpy.da.SearchCursor(
            fc_nha, [FLD_NHA_CLASS, "SHAPE@LENGTH"]) as cur:
        for nha_class, length in cur:
            length = length or 0.0
            nha_total_count += 1
            nha_total_length += length
            bucket = nha_by_class.setdefault(
                nha_class, {"count": 0, "length": 0.0})
            bucket["count"] += 1
            bucket["length"] += length

    osm_total_count = 0
    osm_total_length = 0.0
    osm_by_class = {}

    with arcpy.da.SearchCursor(
            fc_osm, [FLD_OSM_CLASS, "SHAPE@LENGTH"]) as cur:
        for osm_class, length in cur:
            length = length or 0.0
            osm_total_count += 1
            osm_total_length += length
            bucket = osm_by_class.setdefault(
                osm_class, {"count": 0, "length": 0.0})
            bucket["count"] += 1
            bucket["length"] += length

    return {
        "unit_name": unit_name,
        "nha_total_count": nha_total_count,
        "nha_total_length": nha_total_length,
        "nha_by_class": nha_by_class,
        "osm_total_count": osm_total_count,
        "osm_total_length": osm_total_length,
        "osm_by_class": osm_by_class,
        "osm_scope_note": (
            "OSM figures reflect the pre-filtered OSM working copy "
            "(fclass in %s), not the full original OSM dataset."
            % ", ".join(OSM_RELEVANT_FCLASS)),
    }


def compute_review_detail(fc_nha_prepared, nha_name_field):
    """
    Review item #2/#36: for every NHA feature with NHA_Class = 'Review'
    (i.e. no automated classification rule matched - see classify_nha()),
    return the reason (grouped from QC_Note) and the individual feature
    identifiers (Name + source OID), so the report can explain WHY each
    of these features is unresolved rather than just stating a count.

    Also returns the equivalent detail for 'Strategic' features, since
    those are excluded from the Motorway/National-Highway scope for a
    different, non-QC reason (S-series is deliberately not National
    Highway - see classify_nha()) and should not be conflated with
    Review in the report text.
    """
    review_rows = []
    review_reason_tally = {}
    strategic_rows = []

    read_fields = [FLD_NHA_SRC_OID, nha_name_field, FLD_NHA_CLASS, FLD_QC_NOTE]
    with arcpy.da.SearchCursor(fc_nha_prepared, read_fields) as cur:
        for src_oid, name_val, nha_class, qc_note in cur:
            if nha_class == "Review":
                # Group by a short generic reason label (the QC_Note text
                # itself always names the specific feature, so we bucket
                # on the fixed leading phrase from classify_nha() rather
                # than the full note, which would create a distinct
                # "reason" per feature).
                reason = ("No Name-based classification rule matched "
                          "(missing/ambiguous route-code prefix or "
                          "unrecognised named route)")
                review_reason_tally[reason] = review_reason_tally.get(reason, 0) + 1
                review_rows.append((src_oid, name_val or "(blank Name)", qc_note))
            elif nha_class == "Strategic":
                strategic_rows.append((src_oid, name_val or "(blank Name)"))

    return {
        "review_rows": review_rows,
        "review_reason_tally": review_reason_tally,
        "strategic_rows": strategic_rows,
    }



# --------------------------------------------------------------------
# 2. Name and Attribute Matching
# --------------------------------------------------------------------

def compute_name_attribute_matching(fc_final):
    """
    Requirement 2: for each NHA feature in the final (scope-restricted)
    output, classify the name/route-code relationship with its best
    matched OSM feature into one of:
        Exact Match       - normalised route codes are identical
                             (e.g. NHA 'N-5' vs OSM ref 'N5')
        Partial/Similar    - no route-code match, but Match_Status
                             indicates a spatial+class match exists
                             (i.e. the roads correspond, just without a
                             clean route-code confirmation)
        No Attribute Match - no route-code match AND no class-based
                             spatial match (Match_Status is Conflict,
                             SevereMismatch or Unmatched)
        Not Assessable      - no OSM match at all (Unmatched) is folded
                             into 'No Attribute Match' per report
                             requirement to "identify features where
                             attributes do not agree"; Unmatched is
                             additionally counted separately so the two
                             causes (disagreement vs absence) are not
                             conflated.

    NOTE: This function re-derives the route code from NHA_Name because
    X05_Final_Road_Classification stores it as 'NHA_Name'; it relies on
    Match_Status='Matched (Name Confirmed)' (set by Tool 1's
    compare_classifications) as the authoritative signal for an exact
    route-code match, since that status is only ever set when the codes
    matched exactly.

    Road_Name (project requirement: name every road in the final layer
    by combining NHA with its matched OSM feature - e.g. NHA 'N-85'
    matched to OSM ref 'M-2' becomes 'N-85 (OSM: M-2)') is read directly
    from X05_Final_Road_Classification.Road_Name, which was already
    built once by build_road_name() in Tool 1's compare_classifications
    - re-deriving it here from raw OSM attributes would require a second
    join back to X02_OSM_Prepared and could drift out of sync with the
    final layer; reading the already-written field guarantees Stat_
    NameAttributeMatch always shows exactly the same Road_Name a person
    sees when they open X05_Final_Road_Classification's attribute table.
    """
    tally = {
        "Exact Match": 0,
        "Partial/Similar": 0,
        "No Attribute Match": 0,
        "Unmatched (No OSM Feature)": 0,
    }
    detail_rows = []

    read_fields = [FLD_NHA_SRC_OID, "NHA_Name", FLD_NHA_CLASS,
                   FLD_MATCH_STATUS, FLD_OSM_MATCH_ID, FLD_OSM_MATCH_CLASS,
                   FLD_ROAD_TYPE, FLD_ROAD_NAME]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for row in cur:
            (src_oid, nha_name, nha_class, match_status, osm_id, osm_class,
             road_type, road_name) = row

            if match_status == "Unmatched":
                category = "Unmatched (No OSM Feature)"
            elif match_status == "Matched (Name Confirmed)":
                category = "Exact Match"
            elif match_status in ("Matched", "Multiple"):
                category = "Partial/Similar"
            else:
                # Conflict / SevereMismatch
                category = "No Attribute Match"

            tally[category] += 1
            detail_rows.append((src_oid, nha_name, nha_class, match_status,
                                 osm_id, osm_class, category, road_type,
                                 road_name))

    total = sum(tally.values())
    pct = {}
    for key, cnt in tally.items():
        pct[key] = (100.0 * cnt / total) if total > 0 else 0.0

    return {
        "tally": tally,
        "pct": pct,
        "total": total,
        "detail_rows": detail_rows,
    }


# --------------------------------------------------------------------
# 3. Geographic/Spatial Matching Tiers
# --------------------------------------------------------------------

def compute_spatial_matching_tiers(fc_nha, fc_osm, fc_final, workspace):
    """
    Requirement 3: classify each NHA feature (scope-restricted set, from
    fc_final) into one of four spatial relationship tiers with its best
    matched OSM feature:

        Overlapping        - NHA and OSM geometries are essentially
                              coincident (both lines pass within
                              SPATIAL_OVERLAP_TOLERANCE of each other
                              for their full shared extent - measured via
                              a symmetric buffer-intersection test).
        Partially Overlapping - the two lines coincide (within
                              SPATIAL_OVERLAP_TOLERANCE) for at least
                              SPATIAL_PARTIAL_MIN_PCT of the NHA length,
                              but not for the full length.
        Nearby (Non-overlapping) - matched (within Tool 1's matching
                              tolerance) but the coincidence test above
                              finds less than SPATIAL_PARTIAL_MIN_PCT
                              overlap - i.e. the roads are near each
                              other (e.g. parallel carriageways/
                              service roads) but do not track the same
                              alignment.
        Unmatched           - no OSM feature was found within Tool 1's
                              matching tolerance at all.

    METHOD: for each matched (NHA, OSM) pair, the OSM line is buffered by
    SPATIAL_OVERLAP_TOLERANCE and intersected with the NHA line; the
    resulting intersected length as a percentage of the NHA line's total
    length gives the "coincidence percentage" used for tiering. This is
    computed with arcpy.Buffer_analysis + arcpy.Intersect_analysis on the
    (small, already filtered) matched-pair subset only - not looped over
    the full OSM dataset - so it remains fast even though it is doing
    real geometry operations rather than only reading pre-computed fields.
    """
    nha_oid_field = arcpy.Describe(fc_nha).OIDFieldName
    osm_oid_field = arcpy.Describe(fc_osm).OIDFieldName

    # Build quick lookups: NHA Src OID -> geometry, length; OSM working
    # OID -> geometry.
    nha_geom = {}
    nha_length = {}
    with arcpy.da.SearchCursor(
            fc_nha, [nha_oid_field, "SHAPE@", "SHAPE@LENGTH"]) as cur:
        for oid, shape, length in cur:
            nha_geom[oid] = shape
            nha_length[oid] = length or 0.0

    osm_geom = {}
    with arcpy.da.SearchCursor(fc_osm, [osm_oid_field, "SHAPE@"]) as cur:
        for oid, shape in cur:
            osm_geom[oid] = shape

    tally = {
        "Overlapping": 0,
        "Partially Overlapping": 0,
        "Nearby (Non-overlapping)": 0,
        "Unmatched": 0,
    }
    detail_rows = []

    tol_value, tol_unit = _parse_linear_unit(SPATIAL_OVERLAP_TOLERANCE)

    read_fields = [FLD_NHA_SRC_OID, FLD_MATCH_STATUS, FLD_OSM_MATCH_ID]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for src_oid, match_status, osm_id in cur:

            if match_status == "Unmatched" or osm_id is None:
                tally["Unmatched"] += 1
                detail_rows.append((src_oid, "Unmatched", 0.0))
                continue

            nha_shape = nha_geom.get(src_oid)
            osm_shape = osm_geom.get(osm_id)
            if nha_shape is None or osm_shape is None:
                tally["Unmatched"] += 1
                detail_rows.append((src_oid, "Unmatched", 0.0))
                continue

            # Buffer the OSM line by the overlap tolerance and measure
            # what fraction of the NHA line's length falls inside it.
            # Using in-memory geometry buffer/intersect (arcpy geometry
            # objects support .buffer() and .intersect() directly,
            # avoiding the need for on-disk intermediate feature classes
            # for this per-pair test).
            try:
                osm_buffer = osm_shape.buffer(tol_value)
                overlap_geom = nha_shape.intersect(osm_buffer, 2)  # 2 = polyline
                overlap_length = overlap_geom.length if overlap_geom else 0.0
            except Exception:
                overlap_length = 0.0

            nha_len = nha_length.get(src_oid, 0.0)
            coincidence_pct = (100.0 * overlap_length / nha_len) if nha_len > 0 else 0.0

            if coincidence_pct >= 99.0:
                tier = "Overlapping"
            elif coincidence_pct >= SPATIAL_PARTIAL_MIN_PCT:
                tier = "Partially Overlapping"
            else:
                tier = "Nearby (Non-overlapping)"

            tally[tier] += 1
            detail_rows.append((src_oid, tier, coincidence_pct))

    total = sum(tally.values())
    pct = {}
    for key, cnt in tally.items():
        pct[key] = (100.0 * cnt / total) if total > 0 else 0.0

    return {
        "tally": tally,
        "pct": pct,
        "total": total,
        "detail_rows": detail_rows,
        "overlap_tolerance": SPATIAL_OVERLAP_TOLERANCE,
        "partial_min_pct": SPATIAL_PARTIAL_MIN_PCT,
    }


# --------------------------------------------------------------------
# 4. Geometric Alignment Assessment
# --------------------------------------------------------------------

def compute_geometric_alignment(fc_nha, fc_osm, fc_final, workspace):
    """
    Requirement 4: for each matched (NHA, OSM) pair, evaluate how closely
    the OSM geometry follows the NHA alignment using a tiered buffer
    coverage test (distinct from, and stricter/more granular than, the
    binary overlap test in Requirement 3):

        Perfect            - >= ALIGNMENT_MIN_COVERAGE_PCT of NHA length
                              falls within ALIGNMENT_PERFECT_TOLERANCE of
                              the OSM line.
        Slight Deviation   - not Perfect, but >= ALIGNMENT_MIN_COVERAGE_PCT
                              of NHA length falls within
                              ALIGNMENT_SLIGHT_TOLERANCE.
        Significant Deviation - not Slight, but >= ALIGNMENT_MIN_COVERAGE_PCT
                              of NHA length falls within
                              ALIGNMENT_SIGNIFICANT_TOLERANCE.
        Misaligned         - matched, but coverage never reaches
                              ALIGNMENT_MIN_COVERAGE_PCT even at the
                              Significant tolerance.
        Not Assessable     - no OSM match exists at all (Unmatched).

    This reuses the same buffer-and-measure-coverage approach as
    Requirement 3 but at three successive tolerances, so the two
    requirements' outputs are consistent with each other by construction
    while answering different questions (IS there overlap, vs HOW CLOSE
    is the alignment).
    """
    nha_oid_field = arcpy.Describe(fc_nha).OIDFieldName
    osm_oid_field = arcpy.Describe(fc_osm).OIDFieldName

    nha_geom = {}
    nha_length = {}
    with arcpy.da.SearchCursor(
            fc_nha, [nha_oid_field, "SHAPE@", "SHAPE@LENGTH"]) as cur:
        for oid, shape, length in cur:
            nha_geom[oid] = shape
            nha_length[oid] = length or 0.0

    osm_geom = {}
    with arcpy.da.SearchCursor(fc_osm, [osm_oid_field, "SHAPE@"]) as cur:
        for oid, shape in cur:
            osm_geom[oid] = shape

    tier_tolerances = [
        ("Perfect", ALIGNMENT_PERFECT_TOLERANCE),
        ("Slight Deviation", ALIGNMENT_SLIGHT_TOLERANCE),
        ("Significant Deviation", ALIGNMENT_SIGNIFICANT_TOLERANCE),
    ]
    tier_values = {}
    for tier_name, tol_txt in tier_tolerances:
        value, unit = _parse_linear_unit(tol_txt)
        tier_values[tier_name] = value

    tally = {
        "Perfect": 0,
        "Slight Deviation": 0,
        "Significant Deviation": 0,
        "Misaligned": 0,
        "Not Assessable": 0,
    }
    per_feature = {}  # src_oid -> tier (used by Requirement 5)
    detail_rows = []

    read_fields = [FLD_NHA_SRC_OID, FLD_MATCH_STATUS, FLD_OSM_MATCH_ID]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for src_oid, match_status, osm_id in cur:

            if match_status == "Unmatched" or osm_id is None:
                tally["Not Assessable"] += 1
                per_feature[src_oid] = "Not Assessable"
                detail_rows.append((src_oid, "Not Assessable", 0.0))
                continue

            nha_shape = nha_geom.get(src_oid)
            osm_shape = osm_geom.get(osm_id)
            if nha_shape is None or osm_shape is None:
                tally["Not Assessable"] += 1
                per_feature[src_oid] = "Not Assessable"
                detail_rows.append((src_oid, "Not Assessable", 0.0))
                continue

            nha_len = nha_length.get(src_oid, 0.0)
            assigned_tier = "Misaligned"
            best_coverage_pct = 0.0

            for tier_name, tol_txt in tier_tolerances:
                tol_value = tier_values[tier_name]
                try:
                    osm_buffer = osm_shape.buffer(tol_value)
                    overlap_geom = nha_shape.intersect(osm_buffer, 2)
                    overlap_length = overlap_geom.length if overlap_geom else 0.0
                except Exception:
                    overlap_length = 0.0

                coverage_pct = (100.0 * overlap_length / nha_len) if nha_len > 0 else 0.0
                if coverage_pct > best_coverage_pct:
                    best_coverage_pct = coverage_pct

                if coverage_pct >= ALIGNMENT_MIN_COVERAGE_PCT:
                    assigned_tier = tier_name
                    break  # tiers are checked tightest-first; stop at first pass

            tally[assigned_tier] += 1
            per_feature[src_oid] = assigned_tier
            detail_rows.append((src_oid, assigned_tier, best_coverage_pct))

    total = sum(tally.values())
    pct = {}
    for key, cnt in tally.items():
        pct[key] = (100.0 * cnt / total) if total > 0 else 0.0

    return {
        "tally": tally,
        "pct": pct,
        "total": total,
        "per_feature": per_feature,
        "detail_rows": detail_rows,
        "min_coverage_pct_required": ALIGNMENT_MIN_COVERAGE_PCT,
        "tolerances": dict(tier_tolerances),
    }


# --------------------------------------------------------------------
# 5. Perfect Match Identification
# --------------------------------------------------------------------

def compute_perfect_match(fc_final, alignment_per_feature):
    """
    Requirement 5: an NHA feature counts as a "Perfect Match" only if
    ALL of the following hold simultaneously (see
    PERFECT_MATCH_ALIGNMENT_TIERS in Section A.6):
        - Road class agrees (Match_Status in Matched / Multiple /
          Matched (Name Confirmed))
        - Geometric alignment tier (Requirement 4) is 'Perfect'
        - Match_Status is not a class-disagreement outcome (Conflict /
          SevereMismatch) - i.e. identifying attributes are, at minimum,
          not actively contradicted.

    This directly implements "features that simultaneously satisfy the
    predefined criteria for a successful match" - the criteria are
    listed explicitly above rather than left implicit.
    """
    class_agree_statuses = ("Matched", "Multiple", "Matched (Name Confirmed)")

    perfect_count = 0
    total_count = 0
    perfect_oids = []
    perfect_single_correspondence = 0
    perfect_multi_correspondence = 0

    read_fields = [FLD_NHA_SRC_OID, FLD_MATCH_STATUS, FLD_MATCH_COUNT]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for src_oid, match_status, match_count in cur:
            total_count += 1
            alignment_tier = alignment_per_feature.get(src_oid, "Not Assessable")

            is_perfect = (
                match_status in class_agree_statuses and
                alignment_tier in PERFECT_MATCH_ALIGNMENT_TIERS
            )
            if is_perfect:
                perfect_count += 1
                perfect_oids.append(src_oid)
                # Requirement (review item #19): distinguish a Perfect/
                # High-Confidence Match backed by exactly one corresponding
                # OSM segment from one backed by several (Match_Count > 1),
                # since multiple correspondences carry more residual
                # matching ambiguity even when the alignment tier is met.
                if match_count is not None and match_count > 1:
                    perfect_multi_correspondence += 1
                else:
                    perfect_single_correspondence += 1

    pct = (100.0 * perfect_count / total_count) if total_count > 0 else 0.0

    return {
        "perfect_count": perfect_count,
        "total_count": total_count,
        "perfect_single_correspondence": perfect_single_correspondence,
        "perfect_multi_correspondence": perfect_multi_correspondence,
        "pct": pct,
        "perfect_oids": perfect_oids,
        "criteria": [
            "Road class agrees with matched OSM feature "
            "(Match_Status in Matched/Multiple/Matched (Name Confirmed))",
            "Geometric alignment tier is 'Perfect' (>= %.0f%% of NHA "
            "length within %s of OSM geometry)"
            % (ALIGNMENT_MIN_COVERAGE_PCT, ALIGNMENT_PERFECT_TOLERANCE),
        ],
    }


# --------------------------------------------------------------------
# 6. Road Classification Agreement
# --------------------------------------------------------------------

def compute_classification_agreement(fc_final):
    """
    Requirement 6: confusion-matrix style comparison of NHA_Class vs the
    matched OSM_Class, restricted to the two classes of interest. Reports:
        - Motorways correctly identified as Motorway-class OSM
        - National Highways correctly identified as Trunk/Primary-class OSM
          (per NHA_OSM_AGREEMENT - Trunk and Primary are the OSM classes
          that legitimately correspond to National Highway, NOT Motorway)
        - Cross-classification errors: NHA Motorway matched only to a
          National-Highway-tier OSM class (Trunk/Primary) or vice versa
        - Unmatched features per NHA class (no OSM class available to
          compare against at all)
    """
    matrix = {}  # (nha_class, osm_class_or_None) -> count
    nha_totals = {}

    read_fields = [FLD_NHA_CLASS, FLD_MATCH_STATUS, FLD_OSM_MATCH_CLASS]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for nha_class, match_status, osm_class in cur:
            nha_totals[nha_class] = nha_totals.get(nha_class, 0) + 1
            osm_key = osm_class if osm_class else "None (Unmatched)"
            key = (nha_class, osm_key)
            matrix[key] = matrix.get(key, 0) + 1

    # Derived headline figures.
    motorway_total = nha_totals.get("Motorway", 0)
    nh_total = nha_totals.get("National Highway", 0)

    motorway_correct = matrix.get(("Motorway", "Motorway"), 0)
    nh_correct = (matrix.get(("National Highway", "Trunk"), 0) +
                  matrix.get(("National Highway", "Primary"), 0) +
                  matrix.get(("National Highway", "Motorway"), 0))

    # Cross-classification errors: NHA says one thing, matched OSM class
    # corresponds to the OTHER category's expected classes.
    motorway_mis_as_nh_class = (matrix.get(("Motorway", "Trunk"), 0) +
                                 matrix.get(("Motorway", "Primary"), 0))
    nh_mis_as_motorway_class = 0  # Motorway OSM class agrees with NH per
    # NHA_OSM_AGREEMENT, so this is not an error by the current agreement
    # rules; reported as 0 with an explanatory note for transparency.

    motorway_correct_pct = (100.0 * motorway_correct / motorway_total
                             ) if motorway_total > 0 else 0.0
    nh_correct_pct = (100.0 * nh_correct / nh_total) if nh_total > 0 else 0.0

    return {
        "matrix": matrix,
        "nha_totals": nha_totals,
        "motorway_total": motorway_total,
        "motorway_correct": motorway_correct,
        "motorway_correct_pct": motorway_correct_pct,
        "nh_total": nh_total,
        "nh_correct": nh_correct,
        "nh_correct_pct": nh_correct_pct,
        "motorway_mis_as_nh_class": motorway_mis_as_nh_class,
        "nh_mis_as_motorway_class": nh_mis_as_motorway_class,
        "note": (
            "'Correctly identified' means the matched OSM Road_Class is "
            "in the agreement set defined for that NHA_Class in "
            "NHA_OSM_AGREEMENT (Motorway agrees only with OSM Motorway; "
            "National Highway agrees with OSM Trunk, Primary, or "
            "Motorway). An NHA Motorway matched only to OSM Trunk/Primary "
            "is counted as a cross-classification discrepancy, not a "
            "correct match, since Trunk/Primary is the expected OSM tier "
            "for National Highway, not Motorway."),
    }


# --------------------------------------------------------------------
# 7. Mismatch and Error Analysis
# --------------------------------------------------------------------

def compute_mismatch_taxonomy(fc_final, name_match_stats, alignment_stats):
    """
    Requirement 7: quantifies and categorizes all discrepancy types found
    across the analysis into a single taxonomy:
        Name/Attribute Mismatch  - from Requirement 2 ('No Attribute Match')
        Classification Mismatch  - Match_Status in (Conflict, SevereMismatch)
        Spatial/Unmatched        - Match_Status == 'Unmatched'
        Fragmented Representation - Match_Count > 1 (one NHA feature
                                    represented by multiple OSM segments -
                                    reported here as a category, not
                                    necessarily an "error", per Tool 1's
                                    original design; flagged for
                                    completeness of the taxonomy)
        Severe Mismatch (Likely OSM Data Error) - Match_Status ==
                                    'SevereMismatch' specifically (subset
                                    of Classification Mismatch, broken out
                                    because it indicates a likely data
                                    quality problem in OSM rather than a
                                    legitimate classification difference)
        Uncertain/Ambiguous       - NHA_Class == 'Review' (should not
                                    normally appear here since fc_final is
                                    scope-restricted to Motorway/National
                                    Highway, but checked defensively)

    NOTE ON "duplicate representations" and "additional/missing OSM
    features": these two specific sub-requirements require comparison
    against the FULL original OSM dataset (to know about OSM roads with
    no NHA counterpart at all) which is outside the scope of fc_final
    (an NHA-feature-per-row table). They are addressed separately and
    explicitly in Requirement 8 (NHA completeness) using fc_final, and
    are flagged here as NOT computed from OSM's side within this
    function, to avoid silently underreporting "additional OSM
    features" as zero.
    """
    tally = {
        "Name/Attribute Mismatch": 0,
        "Classification Mismatch": 0,
        "Spatial/Unmatched": 0,
        "Fragmented Representation (Match_Count > 1)": 0,
        "Severe Mismatch (Likely OSM Data Error)": 0,
        "Uncertain/Ambiguous (Review)": 0,
    }

    read_fields = [FLD_NHA_CLASS, FLD_MATCH_STATUS, FLD_MATCH_COUNT]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for nha_class, match_status, match_count in cur:
            if match_status in ("Conflict", "SevereMismatch"):
                tally["Classification Mismatch"] += 1
            if match_status == "SevereMismatch":
                tally["Severe Mismatch (Likely OSM Data Error)"] += 1
            if match_status == "Unmatched":
                tally["Spatial/Unmatched"] += 1
            if match_count and match_count > 1:
                tally["Fragmented Representation (Match_Count > 1)"] += 1
            if nha_class == "Review":
                tally["Uncertain/Ambiguous (Review)"] += 1

    tally["Name/Attribute Mismatch"] = name_match_stats["tally"].get(
        "No Attribute Match", 0)

    return {
        "tally": tally,
        "scope_note": (
            "'Additional OSM features' (OSM roads with no NHA "
            "counterpart) and 'duplicate representations' on the OSM "
            "side are not computable from X05_Final_Road_Classification "
            "alone, since it is one row per NHA feature. See Requirement "
            "8 (Network Completeness) for the NHA-side completeness "
            "figure, which is the mirror-image statistic that IS "
            "computable from the current outputs."),
    }


# --------------------------------------------------------------------
# 8. NHA Reference Network Completeness in OSM
# --------------------------------------------------------------------

def compute_network_completeness(fc_final):
    """
    Requirement 8: what fraction of the authoritative NHA network (by
    feature count) has ANY corresponding OSM feature, regardless of
    whether that correspondence is a class match or a conflict - i.e.
    "represented in OSM at all" is a strictly spatial question here
    (Match_Status != 'Unmatched'), separate from whether the
    representation agrees in classification.
    """
    represented = {"Motorway": 0, "National Highway": 0}
    absent = {"Motorway": 0, "National Highway": 0}
    absent_names = {"Motorway": [], "National Highway": []}

    read_fields = [FLD_NHA_CLASS, "NHA_Name", FLD_MATCH_STATUS]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for nha_class, nha_name, match_status in cur:
            if nha_class not in represented:
                continue
            if match_status == "Unmatched":
                absent[nha_class] += 1
                absent_names[nha_class].append(nha_name)
            else:
                represented[nha_class] += 1

    result = {}
    for cls in ("Motorway", "National Highway"):
        total = represented[cls] + absent[cls]
        pct = (100.0 * represented[cls] / total) if total > 0 else 0.0
        result[cls] = {
            "represented_count": represented[cls],
            "absent_count": absent[cls],
            "total_count": total,
            "represented_pct": pct,
            "absent_names": absent_names[cls],
        }
    return result


# --------------------------------------------------------------------
# 9. Length-Based Network Comparison
# --------------------------------------------------------------------

def compute_length_comparison(fc_nha, fc_osm, fc_final):
    """
    Requirement 9: total NHA reference length vs total OSM length, by
    class, and what percentage of NHA reference length is "represented"
    by OSM. Two length figures are reported for OSM correspondence:

        - matched_osm_length: sum of SHAPE@LENGTH for the actual matched
          OSM features (best match per NHA feature) - this is OSM's own
          geometry length, which may differ from NHA's length due to
          digitizing differences, so it is reported as its own figure,
          not assumed equal to NHA length.
        - nha_length_represented: sum of NHA SHAPE@LENGTH for NHA
          features that have ANY OSM match (i.e. the NHA-side length
          that OSM can be said to "cover"), used for the % coverage
          figure requested ("percentage of NHA reference network length
          represented by OSM") since that phrasing is about NHA length
          being covered, not about summing OSM segment lengths (which
          would double distances where fragmentation exists).
    """
    nha_oid_field = arcpy.Describe(fc_nha).OIDFieldName
    nha_length_lookup = {}
    with arcpy.da.SearchCursor(
            fc_nha, [nha_oid_field, "SHAPE@LENGTH"]) as cur:
        for oid, length in cur:
            nha_length_lookup[oid] = length or 0.0

    osm_oid_field = arcpy.Describe(fc_osm).OIDFieldName
    osm_length_lookup = {}
    with arcpy.da.SearchCursor(
            fc_osm, [osm_oid_field, "SHAPE@LENGTH"]) as cur:
        for oid, length in cur:
            osm_length_lookup[oid] = length or 0.0

    result = {}
    for target_class in ("Motorway", "National Highway"):
        nha_total_length = 0.0
        nha_represented_length = 0.0
        matched_osm_length = 0.0
        matched_osm_oids_seen = set()

        read_fields = [FLD_NHA_SRC_OID, FLD_NHA_CLASS, FLD_MATCH_STATUS,
                       FLD_OSM_MATCH_ID]
        with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
            for src_oid, nha_class, match_status, osm_id in cur:
                if nha_class != target_class:
                    continue
                nha_len = nha_length_lookup.get(src_oid, 0.0)
                nha_total_length += nha_len

                if match_status != "Unmatched":
                    nha_represented_length += nha_len
                    if osm_id is not None and osm_id not in matched_osm_oids_seen:
                        matched_osm_oids_seen.add(osm_id)
                        matched_osm_length += osm_length_lookup.get(osm_id, 0.0)

        pct_represented = (100.0 * nha_represented_length / nha_total_length
                            ) if nha_total_length > 0 else 0.0

        result[target_class] = {
            "nha_total_length": nha_total_length,
            "nha_represented_length": nha_represented_length,
            "pct_length_represented": pct_represented,
            "matched_osm_length": matched_osm_length,
            "matched_osm_feature_count": len(matched_osm_oids_seen),
        }

    return result


# --------------------------------------------------------------------
# 10. OSM Feature Fragmentation and Representation
# --------------------------------------------------------------------

def compute_fragmentation(fc_final):
    """
    Requirement 10: for each NHA feature, Match_Count already records how
    many OSM segments were found within tolerance (computed in Tool 1).
    This function summarizes that distribution: how many NHA features
    are represented by exactly one OSM segment vs multiple, the average
    segments-per-matched-feature, and a categorical fragmentation level.
    """
    single_segment = 0
    multi_segment = 0
    unmatched = 0
    match_counts = []

    read_fields = [FLD_MATCH_COUNT, FLD_MATCH_STATUS]
    with arcpy.da.SearchCursor(fc_final, read_fields) as cur:
        for match_count, match_status in cur:
            if match_status == "Unmatched" or not match_count:
                unmatched += 1
                continue
            match_counts.append(match_count)
            if match_count == 1:
                single_segment += 1
            else:
                multi_segment += 1

    matched_total = len(match_counts)
    avg_segments = (sum(match_counts) / float(matched_total)
                     ) if matched_total > 0 else 0.0
    max_segments = max(match_counts) if match_counts else 0

    multi_pct = (100.0 * multi_segment / matched_total
                 ) if matched_total > 0 else 0.0

    if multi_pct < 10.0:
        fragmentation_level = "Low"
    elif multi_pct < 30.0:
        fragmentation_level = "Moderate"
    else:
        fragmentation_level = "High"

    return {
        "single_segment_count": single_segment,
        "multi_segment_count": multi_segment,
        "unmatched_count": unmatched,
        "matched_total": matched_total,
        "avg_segments_per_matched_feature": avg_segments,
        "max_segments_for_one_feature": max_segments,
        "multi_segment_pct_of_matched": multi_pct,
        "fragmentation_level": fragmentation_level,
    }


# --------------------------------------------------------------------
# 11. Spatial Accuracy and Positional Deviation
# --------------------------------------------------------------------

def compute_positional_accuracy(fc_nha, fc_osm, workspace, tolerance_txt):
    """
    Requirement 11: positional deviation between each NHA feature and its
    single CLOSEST OSM feature (regardless of class agreement - this is a
    pure geometric distance question, distinct from the classification-
    aware Match_Status used elsewhere). Uses Generate Near Table with
    closest='CLOSEST' (single nearest neighbour only, unlike Tool 1's
    matching step which deliberately used closest='ALL') because a
    positional accuracy statistic needs exactly one distance per NHA
    feature, not a set of candidate distances.

    Reports: mean, median, minimum, maximum distance, and the percentage
    of NHA features whose nearest OSM feature is within
    POSITIONAL_TOLERANCE_METERS (or the tolerance passed in).

    Median is computed manually (sorted list, midpoint) since
    arcpy.Statistics_analysis at 10.8 does not provide a MEDIAN
    statistic type - this avoids silently reporting an unsupported
    statistic or approximating it incorrectly.
    """
    tbl_pos = os.path.join(workspace, "X06_Positional_NearTable")
    if arcpy.Exists(tbl_pos):
        arcpy.Delete_management(tbl_pos)

    # Use a generous search radius (10x the requested tolerance, minimum
    # 1000m) so that NHA features whose nearest OSM feature lies beyond
    # the "acceptable" tolerance are still measured (not simply dropped),
    # which is required to compute a true maximum and an honest % within
    # tolerance denominator.
    tol_value, tol_unit = _parse_linear_unit(tolerance_txt)
    search_radius_txt = "%s %s" % (str(max(tol_value * 10, 1000)), tol_unit)

    arcpy.GenerateNearTable_analysis(
        in_features=fc_nha,
        near_features=fc_osm,
        out_table=tbl_pos,
        search_radius=search_radius_txt,
        location="NO_LOCATION",
        angle="NO_ANGLE",
        closest="CLOSEST",
        closest_count=1,
        method="PLANAR")

    distances = []
    with arcpy.da.SearchCursor(tbl_pos, ["NEAR_DIST"]) as cur:
        for row in cur:
            if row[0] is not None and row[0] >= 0:
                distances.append(row[0])

    nha_total = int(arcpy.GetCount_management(fc_nha).getOutput(0))
    no_osm_within_search = nha_total - len(distances)

    if arcpy.Exists(tbl_pos):
        arcpy.Delete_management(tbl_pos)

    if not distances:
        return {
            "mean": None, "median": None, "min": None, "max": None,
            "count_measured": 0, "count_no_osm_in_search_radius": nha_total,
            "pct_within_tolerance": 0.0,
            "tolerance_used": tolerance_txt,
            "distances": [],
            "note": "No NHA-OSM distances could be measured within the "
                    "search radius used.",
        }

    distances_sorted = sorted(distances)
    n = len(distances_sorted)
    mean_val = sum(distances_sorted) / float(n)
    if n % 2 == 1:
        median_val = distances_sorted[n // 2]
    else:
        median_val = (distances_sorted[n // 2 - 1] + distances_sorted[n // 2]) / 2.0
    min_val = distances_sorted[0]
    max_val = distances_sorted[-1]

    tol_value_m, _ = _parse_linear_unit(tolerance_txt)
    within_tolerance = sum(1 for d in distances_sorted if d <= tol_value_m)
    pct_within_tolerance = 100.0 * within_tolerance / n

    return {
        "mean": mean_val,
        "median": median_val,
        "min": min_val,
        "max": max_val,
        "count_measured": n,
        "count_no_osm_in_search_radius": no_osm_within_search,
        "within_tolerance_count": within_tolerance,
        "pct_within_tolerance": pct_within_tolerance,
        "tolerance_used": tolerance_txt,
        "distances": distances_sorted,
    }


# --------------------------------------------------------------------
# 12. Overall Classification and Data Quality Assessment
# --------------------------------------------------------------------

def compute_overall_quality_assessment(stats):
    """
    Requirement 12: a single composite assessment combining the above
    eleven sections into headline scores and a qualitative rating.

    The composite score is a simple, EXPLICIT, equally-weighted average
    of five normalized sub-scores (each 0-100), chosen so the formula is
    fully transparent and auditable rather than a hidden black-box index:

        1. Classification Accuracy Score = weighted avg of
           Motorway_correct_pct and NationalHighway_correct_pct
           (weighted by each class's feature count)
        2. Spatial Match Score = % of features that are Overlapping or
           Partially Overlapping (Requirement 3)
        3. Alignment Score = % of features that are Perfect or Slight
           Deviation (Requirement 4)
        4. Completeness Score = weighted avg of the two
           represented_pct values from Requirement 8 (weighted by
           feature count)
        5. Perfect Match Score = pct from Requirement 5 directly

    Overall_Quality_Score = simple average of the five scores above.

    Qualitative rating bands (explicit, editable):
        >= 85  -> "Excellent"
        70-84  -> "Good"
        50-69  -> "Fair"
        < 50   -> "Poor"

    This is a SUMMARY indicator only - the full report retains every
    underlying figure so the composite is never the only thing a reader
    can inspect.
    """
    class_agree = stats["class_agreement"]
    mw_total = class_agree["motorway_total"]
    nh_total = class_agree["nh_total"]
    total_class_features = mw_total + nh_total
    if total_class_features > 0:
        classification_score = (
            (class_agree["motorway_correct_pct"] * mw_total +
             class_agree["nh_correct_pct"] * nh_total) / total_class_features)
    else:
        classification_score = 0.0

    spatial = stats["spatial_match"]
    spatial_score = spatial["pct"].get("Overlapping", 0.0) + \
        spatial["pct"].get("Partially Overlapping", 0.0)

    alignment = stats["alignment"]
    alignment_score = alignment["pct"].get("Perfect", 0.0) + \
        alignment["pct"].get("Slight Deviation", 0.0)

    completeness = stats["completeness"]
    comp_mw = completeness.get("Motorway", {})
    comp_nh = completeness.get("National Highway", {})
    comp_mw_total = comp_mw.get("total_count", 0)
    comp_nh_total = comp_nh.get("total_count", 0)
    comp_denom = comp_mw_total + comp_nh_total
    if comp_denom > 0:
        completeness_score = (
            (comp_mw.get("represented_pct", 0.0) * comp_mw_total +
             comp_nh.get("represented_pct", 0.0) * comp_nh_total) / comp_denom)
    else:
        completeness_score = 0.0

    perfect_match_score = stats["perfect_match"]["pct"]

    overall_score = (classification_score + spatial_score +
                      alignment_score + completeness_score +
                      perfect_match_score) / 5.0

    if overall_score >= 85.0:
        rating = "Excellent"
    elif overall_score >= 70.0:
        rating = "Good"
    elif overall_score >= 50.0:
        rating = "Fair"
    else:
        rating = "Poor"

    return {
        "classification_score": classification_score,
        "spatial_score": spatial_score,
        "alignment_score": alignment_score,
        "completeness_score": completeness_score,
        "perfect_match_score": perfect_match_score,
        "overall_score": overall_score,
        "rating": rating,
        "formula_note": (
            "Overall_Quality_Score = average of 5 equally-weighted "
            "sub-scores: Classification Accuracy, Spatial Match, "
            "Geometric Alignment, Network Completeness, Perfect Match "
            "percentage. See function docstring for exact sub-score "
            "definitions."),
    }


# --------------------------------------------------------------------
# Report writer
# --------------------------------------------------------------------

def _fmt(value, decimals=1):
    """Safe numeric formatter for the report (Python 2.7 %-style)."""
    if value is None:
        return "N/A"
    fmt_str = "%%.%df" % decimals
    return fmt_str % value


# Python 2/3 compatible text-type aliases. This toolbox targets ArcMap
# 10.8's Python 2.7, where 'unicode' and 'str' are distinct types; under
# Python 3 (e.g. if ever migrated to ArcGIS Pro, or run outside ArcMap
# for testing) 'unicode' does not exist at all. Resolving this once here
# means _safe_unicode() below works correctly - and is testable - under
# either interpreter, rather than hard-failing on a Python-2-only name.
try:
    _TEXT_TYPE = unicode      # Python 2
    _BINARY_TYPE = str
except NameError:
    _TEXT_TYPE = str          # Python 3
    _BINARY_TYPE = bytes


def _safe_unicode(value):
    """
    Coerces any report line (str, unicode/bytes, or None) to a proper
    text object, decoding byte strings as UTF-8 if needed. Field values
    pulled from the geodatabase (e.g. NHA/OSM 'Name' or 'ref') can
    legitimately contain non-ASCII characters - accented letters,
    en/em-dashes, Urdu/Arabic script, etc. - and Python 2's implicit
    str<->unicode coercion silently assumes ASCII, which raises
    UnicodeEncodeError / UnicodeDecodeError the moment such a character
    appears. Every line written to the report (plain-text or PDF) is
    passed through this function so a single unusual character in
    source data can never crash report generation.
    """
    if value is None:
        return u""
    if isinstance(value, _TEXT_TYPE):
        return value
    try:
        # value is a byte string here - try UTF-8 first, since ArcGIS
        # geodatabases store text as UTF-8/Unicode internally.
        return value.decode("utf-8")
    except UnicodeDecodeError:
        # Last resort: decode leniently rather than crash the whole run
        # over a single unreadable byte in one feature's Name field.
        return value.decode("utf-8", "replace")
    except AttributeError:
        # Not a string at all (shouldn't normally reach here since all
        # report lines are pre-formatted strings) - fall back to str().
        return _TEXT_TYPE(value)


# Report-facing display labels for internal status/tier codes (review
# items #1, #3, #6, #11, #14, #31-#34). These affect ONLY the text
# rendered in the Final Statistical Summary report; the underlying
# NHA_Class / Match_Status / Spatial_Tier / Alignment_Tier values stored
# in the geodatabase (X01_NHA_Prepared, X05_Final_Road_Classification,
# Stat_* tables) are left unchanged, since other parts of this tool and
# any existing saved queries/definition-expressions depend on the exact
# stored strings ("Review", "Unmatched", "Nearby (Non-overlapping)",
# "Perfect", etc.). Renaming the underlying codes would be a breaking
# change to the geodatabase schema; renaming only the report prose is not.
REPORT_DISPLAY_LABELS = {
    "Review": "Features Requiring Classification Review",
    "Unmatched (No OSM Feature)": "NHA Reference Features Without a Corresponding OSM Feature",
    "Unmatched": "NHA Reference Features Without a Corresponding OSM Feature",
    "Nearby (Non-overlapping)": "Spatially Proximate, Non-overlapping",
    "Perfect": "High Alignment (5 m Tier)",
    "Perfect Match": "High-Confidence Match",
}


def _label(key):
    """Look up a review-friendly display label for a report line; falls
    back to the raw internal value unchanged if no remapping is defined."""
    return REPORT_DISPLAY_LABELS.get(key, key)


def _build_report_sections(stats, workspace):
    """
    Builds the thirteen report sections as a list of
    (heading, [line, line, ...]) tuples, shared by both the PDF writer
    and the plain-text fallback writer so the two formats never drift
    out of sync with each other.
    """
    inv = stats["inventory"]
    review_detail = stats.get("review_detail", {"review_rows": [],
                                                  "review_reason_tally": {},
                                                  "strategic_rows": []})
    name_match = stats["name_match"]
    spatial = stats["spatial_match"]
    alignment = stats["alignment"]
    perfect = stats["perfect_match"]
    class_agree = stats["class_agreement"]
    mismatch = stats["mismatch"]
    completeness = stats["completeness"]
    length_comp = stats["length_comparison"]
    frag = stats["fragmentation"]
    pos = stats["positional"]
    overall = stats["overall"]

    sections = []

    # ---- 0. Scope Statement (review item #30) ----
    lines = []
    lines.append("This report covers %d NHA reference features in total. "
                  "Of these, %d (Motorway + National Highway) fall within "
                  "the Motorway/National-Highway comparison scope used by "
                  "Sections 2-10 and 12; the remaining %d are Strategic "
                  "roads or Features Requiring Classification Review and "
                  "are excluded from that comparison (see Section 1 for the "
                  "breakdown and reasons). Section 11 (positional accuracy) "
                  "is the one exception and is built from all %d features. "
                  "Wherever a percentage appears below, its denominator is "
                  "stated alongside it (e.g. 'X / 78', 'X / 121', 'X of 20 "
                  "Motorways') - always check the stated denominator before "
                  "comparing percentages across sections (review item #29)."
                  % (inv["nha_total_count"],
                     sum(inv["nha_by_class"].get(c, {"count": 0})["count"]
                         for c in FINAL_OUTPUT_CLASSES),
                     inv["nha_total_count"] - sum(
                         inv["nha_by_class"].get(c, {"count": 0})["count"]
                         for c in FINAL_OUTPUT_CLASSES),
                     inv["nha_total_count"]))
    sections.append(("0. Scope Statement", lines))

    # ---- 1. Inventory ----
    lines = []
    lines.append("Units: %s" % inv["unit_name"])
    lines.append("NHA reference features (total): %d  (total length: %s %s)"
                  % (inv["nha_total_count"], _fmt(inv["nha_total_length"]),
                     inv["unit_name"]))
    # Report EVERY NHA_Class bucket present in the prepared dataset (not
    # just Motorway/National Highway), so the total feature count and
    # total length above are always fully reconciled against the classes
    # listed below - Strategic and Review features are computed upstream
    # (see OUTPUT SCOPE in the module docstring) but are excluded from the
    # scope-restricted X05_Final_Road_Classification / Classification_Summary
    # deliverables. Listing them here prevents the apparent "121 total vs
    # 78 classified" discrepancy raised in review: the remaining features
    # are Strategic and/or Review, not lost or undocumented.
    _preferred_order = ["Motorway", "National Highway", "Strategic", "Review"]
    _remaining_classes = [c for c in inv["nha_by_class"].keys()
                           if c not in _preferred_order]
    for cls in _preferred_order + sorted(_remaining_classes):
        if cls not in inv["nha_by_class"]:
            continue
        b = inv["nha_by_class"][cls]
        in_scope_note = "" if cls in FINAL_OUTPUT_CLASSES else \
            " [excluded from X05/Classification_Summary - see notes below]"
        display_cls = _label(cls) if cls == "Review" else cls
        lines.append("  NHA %s: %d features, %s %s%s"
                      % (display_cls, b["count"], _fmt(b["length"]),
                         inv["unit_name"], in_scope_note))
    lines.append("Note: %d of the %d total NHA features (%s %s of length) are "
                  "Strategic roads and/or Features Requiring Classification "
                  "Review (no confident NHA_Class prefix match) and are "
                  "intentionally out of scope for the Motorway/National-"
                  "Highway comparison in Sections 2-10 and 12 below; see the "
                  "module docstring 'OUTPUT SCOPE' for the rule. This is why "
                  "Sections 2-10 and 12 use a denominator of %d (the "
                  "scope-restricted count), while Section 11 (built directly "
                  "from X01_NHA_Prepared) uses the full %d."
                  % (inv["nha_total_count"] - sum(
                         inv["nha_by_class"].get(c, {"count": 0})["count"]
                         for c in FINAL_OUTPUT_CLASSES),
                     inv["nha_total_count"],
                     _fmt(inv["nha_total_length"] - sum(
                         inv["nha_by_class"].get(c, {"length": 0.0})["length"]
                         for c in FINAL_OUTPUT_CLASSES)),
                     inv["unit_name"],
                     sum(inv["nha_by_class"].get(c, {"count": 0})["count"]
                         for c in FINAL_OUTPUT_CLASSES),
                     inv["nha_total_count"]))
    # Strategic feature identifiers (review item #37-style traceability,
    # applied here to Strategic as well as Review).
    strategic_rows = review_detail["strategic_rows"]
    if strategic_rows:
        lines.append("  Strategic (S-series) features excluded by design "
                      "(not National Highway, per explicit rule): %s"
                      % ", ".join("%s (OID %s)" % (n, oid)
                                   for oid, n in strategic_rows))
    # Review reason breakdown + individual feature list (review items #2, #36).
    review_rows = review_detail["review_rows"]
    review_reason_tally = review_detail["review_reason_tally"]
    if review_rows:
        lines.append("  %s: %d features. Reason breakdown:"
                      % (_label("Review"), len(review_rows)))
        for reason, cnt in review_reason_tally.items():
            lines.append("    - %s: %d" % (reason, cnt))
        lines.append("    Unresolved feature list (Name (Source OID)): %s"
                      % ", ".join("%s (%s)" % (n, oid)
                                   for oid, n, _note in review_rows))
    lines.append("")
    lines.append("OSM candidate features (total, pre-filtered scope): %d "
                  "(total length: %s %s)"
                  % (inv["osm_total_count"], _fmt(inv["osm_total_length"]),
                     inv["unit_name"]))
    for cls in ("Motorway", "Trunk", "Primary"):
        b = inv["osm_by_class"].get(cls, {"count": 0, "length": 0.0})
        lines.append("  OSM %s: %d features, %s %s"
                      % (cls, b["count"], _fmt(b["length"]), inv["unit_name"]))
    lines.append("Note: %s" % inv["osm_scope_note"])
    sections.append(("1. Dataset Inventory and Baseline Statistics", lines))

    # ---- 2. Name/Attribute Matching ----
    lines = []
    for key in ("Exact Match", "Partial/Similar", "No Attribute Match",
                "Unmatched (No OSM Feature)"):
        display_key = _label(key) if key == "Unmatched (No OSM Feature)" else key
        lines.append("%s: %d  (%s%%)"
                      % (display_key, name_match["tally"][key],
                         _fmt(name_match["pct"][key])))
    lines.append("Total assessed: %d" % name_match["total"])
    lines.append("Note: name/route-code matching (Exact Match / Partial/"
                  "Similar) is supporting evidence only, per Section A.3.1 "
                  "of the tool configuration - it can upgrade a spatial "
                  "match's confidence but is never by itself proof that two "
                  "geometries represent the same road (review item #17). "
                  "'Exact Match' requires the normalised route code (see "
                  "extract_route_code(): uppercased, whitespace/hyphens "
                  "stripped) to match identically between NHA Name and OSM "
                  "ref/name. 'Partial/Similar' is everything else that still "
                  "has a class-based spatial match (Match_Status "
                  "Matched/Multiple) without that exact code match - it is "
                  "NOT currently based on fuzzy/normalized name similarity, "
                  "only on the presence vs. absence of the exact route-code "
                  "confirmation (review item #18).")
    sections.append(("2. Name and Attribute Matching", lines))

    # ---- 3. Spatial Matching Tiers ----
    lines = []
    lines.append("Overlap tolerance: %s | Partial-overlap threshold: %s%% "
                  "of NHA length" % (spatial["overlap_tolerance"],
                                      _fmt(spatial["partial_min_pct"], 0)))
    for key in ("Overlapping", "Partially Overlapping",
                "Nearby (Non-overlapping)", "Unmatched"):
        lines.append("%s: %d  (%s%%)"
                      % (_label(key), spatial["tally"][key], _fmt(spatial["pct"][key])))
    lines.append("Note: '%s' (formerly 'Nearby') means an OSM candidate "
                  "exists within the matching tolerance used by Generate "
                  "Near Table but the geometries do not coincide/overlap - "
                  "this is a PROXIMITY relationship, not a coverage/overlap "
                  "relationship, and is a different concept from the "
                  "distance-to-nearest-feature statistic in Section 11 "
                  "(review item #5)." % _label("Nearby (Non-overlapping)"))
    lines.append("Note: '%s' in this section means no OSM candidate at all "
                  "was found within tolerance (the NHA<->OSM direction); "
                  "this report does not compute the reverse OSM-to-NHA "
                  "direction (review items #3, #4) - see Section 13(f)."
                  % _label("Unmatched"))
    sections.append(("3. Geographic/Spatial Matching", lines))

    # ---- 4. Geometric Alignment ----
    lines = []
    lines.append("Tiers require >= %s%% of NHA length within tolerance:"
                  % _fmt(alignment["min_coverage_pct_required"], 0))
    lines.append("Perfect tolerance: %s | Slight: %s | Significant: %s"
                  % (ALIGNMENT_PERFECT_TOLERANCE, ALIGNMENT_SLIGHT_TOLERANCE,
                     ALIGNMENT_SIGNIFICANT_TOLERANCE))
    for key in ("Perfect", "Slight Deviation", "Significant Deviation",
                "Misaligned", "Not Assessable"):
        lines.append("%s: %d  (%s%%)"
                      % (_label(key), alignment["tally"][key], _fmt(alignment["pct"][key])))
    lines.append("Note: '%s' (formerly labelled 'Perfect') is a defined "
                  "tier requiring >=60%% of NHA length within 5 m, not a "
                  "claim of exact geometric identity - up to 40%% of a "
                  "feature's length may fall outside the 5 m tolerance "
                  "(review item #6). See Section 13 for the rationale "
                  "behind the 5/15/50 m thresholds." % _label("Perfect"))
    sections.append(("4. Geometric Alignment Assessment", lines))

    # ---- 5. Perfect Match ----
    lines = []
    lines.append("Criteria (ALL must hold):")
    for c in perfect["criteria"]:
        lines.append("- %s" % c)
    lines.append("%s features: %d / %d  (%s%%)"
                  % (_label("Perfect Match"), perfect["perfect_count"], perfect["total_count"],
                     _fmt(perfect["pct"])))
    lines.append("  Of these, backed by exactly 1 corresponding OSM segment "
                  "(Match_Count = 1): %d; backed by multiple corresponding "
                  "OSM segments (Match_Count > 1): %d - multiple-"
                  "correspondence matches carry more residual matching "
                  "ambiguity even though they meet the alignment/class "
                  "criteria above (review item #19)."
                  % (perfect.get("perfect_single_correspondence", 0),
                     perfect.get("perfect_multi_correspondence", 0)))
    lines.append("Note: renamed from 'Perfect Match' to '%s' in this report "
                  "because the criteria establish a defined confidence tier, "
                  "not mathematical geometric identity (review item #34)."
                  % _label("Perfect Match"))
    sections.append(("5. Perfect Match Identification", lines))

    # ---- 6. Classification Agreement ----
    lines = []
    lines.append("Motorway: %d total, %d agree with NHA_Class under the "
                  "defined OSM crosswalk as OSM Motorway (%s%%)"
                  % (class_agree["motorway_total"], class_agree["motorway_correct"],
                     _fmt(class_agree["motorway_correct_pct"])))
    lines.append("National Highway: %d total, %d agree with NHA_Class under "
                  "the defined OSM crosswalk as OSM Trunk/Primary/Motorway "
                  "(%s%%)"
                  % (class_agree["nh_total"], class_agree["nh_correct"],
                     _fmt(class_agree["nh_correct_pct"])))
    lines.append("Motorway mis-matched to National-Highway-tier OSM class "
                  "(Trunk/Primary): %d" % class_agree["motorway_mis_as_nh_class"])
    lines.append("Note: %s" % class_agree["note"])
    lines.append("Note: these figures are 'NHA-OSM Classification Agreement' "
                  "under the project's editable NHA_OSM_AGREEMENT crosswalk "
                  "(Section A.3 of the tool) - i.e. agreement with the NHA "
                  "reference classification as OSM tags it, NOT an "
                  "independently verified absolute classification accuracy "
                  "against ground truth (review item #20). The crosswalk "
                  "reflects observed OSM tagging practice in Pakistan "
                  "(motorways consistently tagged 'motorway'; national "
                  "highways inconsistently split across 'trunk'/'primary') "
                  "and should be cited as an analytical convention, not an "
                  "inherent equivalence between the two classification "
                  "systems (review item #8).")
    sections.append(("6. Road Classification Agreement", lines))

    # ---- 7. Mismatch Taxonomy ----
    lines = []
    for key, cnt in mismatch["tally"].items():
        lines.append("%s: %d" % (key, cnt))
    lines.append("Note: %s" % mismatch["scope_note"])
    lines.append("Note: 'Severe Mismatch' here means an NHA Motorway/National "
                  "Highway matched only to an OSM Residential/Service/"
                  "Unclassified road (NHA_OSM_SEVERE_MISMATCH) - a zero count "
                  "reflects that this specific, narrowly-defined condition "
                  "did not occur, not a general absence of spatial "
                  "discrepancy. The 54 Misaligned and 58 Nearby-but-"
                  "non-overlapping features above are real, separately-"
                  "reported discrepancies of a different kind (positional, "
                  "not classification) and are not folded into this count.")
    lines.append("Note: 'Classification Mismatch' (road-class disagreement) "
                  "and 'Spatial/Unmatched' (positional/coverage disagreement) "
                  "are intentionally kept as independent tally rows above, "
                  "not combined, since a road can be spatially correct but "
                  "misclassified, or correctly classified but geometrically "
                  "misaligned (review item #35).")
    sections.append(("7. Mismatch and Error Analysis", lines))

    # ---- 8. Network Completeness ----
    lines = []
    for cls in ("Motorway", "National Highway"):
        c = completeness[cls]
        lines.append("%s: %d / %d represented in OSM (%s%%); %d NHA "
                      "reference feature(s) with no corresponding OSM "
                      "feature identified"
                      % (cls, c["represented_count"], c["total_count"],
                         _fmt(c["represented_pct"]), c["absent_count"]))
        if c["absent_names"]:
            names_str = ", ".join([n for n in c["absent_names"] if n])
            if names_str:
                lines.append("  NHA reference feature(s) with no "
                              "corresponding OSM feature under the defined "
                              "matching criteria: %s" % names_str)
    lines.append("Note: 'represented in OSM' / 'absent' describe the "
                  "NHA-to-OSM direction only (review item #37) - i.e. "
                  "whether at least one OSM candidate was found within "
                  "tolerance for that NHA feature, not a statement that the "
                  "road itself is missing from the ground or from OSM "
                  "entirely (it may simply be tagged outside the "
                  "OSM_RELEVANT_FCLASS pre-filter, or split/mis-tagged).")
    sections.append(("8. NHA Reference Network Completeness in OSM", lines))

    # ---- 9. Length Comparison ----
    lines = []
    lines.append("9a. NHA reference length with OSM spatial coverage "
                  "(review item #11 - renamed from 'Represented by OSM'):")
    for cls in ("Motorway", "National Highway"):
        L = length_comp[cls]
        lines.append("  %s: NHA total length %s %s; covered %s %s "
                      "(%s%% of NHA length)"
                      % (cls, _fmt(L["nha_total_length"]), inv["unit_name"],
                         _fmt(L["nha_represented_length"]), inv["unit_name"],
                         _fmt(L["pct_length_represented"])))
    lines.append("")
    lines.append("9b. Raw summed length of matched OSM segments (review "
                  "item #12 - reported separately, NOT beside 9a, because "
                  "the two are not comparable quantities):")
    for cls in ("Motorway", "National Highway"):
        L = length_comp[cls]
        lines.append("  %s: %s %s across %d OSM segments"
                      % (cls, _fmt(L["matched_osm_length"]), inv["unit_name"],
                         L["matched_osm_feature_count"]))
    lines.append("Note: 9a is the NHA-side length that has at least one OSM "
                  "candidate within tolerance (a coverage measure). 9b is the "
                  "raw sum of the individual OSM segment lengths used as "
                  "matching evidence - since OSM splits roads into many "
                  "short segments (see Section 10), 9b is a segment-count-"
                  "driven quantity, not a coverage percentage, and must not "
                  "be read as '2.7M m of NHA motorway is only represented by "
                  "225k m of OSM' (review items #12, #13). Neither figure "
                  "here resolves overlapping/duplicate OSM segments into a "
                  "single unique corresponding network length - that would "
                  "require an additional geometry-dissolve/overlap-"
                  "resolution step not currently performed (review item #13).")
    sections.append(("9. Length-Based Network Comparison", lines))

    # ---- 10. Fragmentation ----
    lines = []
    lines.append("NHA features matched by exactly 1 OSM segment: %d"
                  % frag["single_segment_count"])
    lines.append("NHA features matched by multiple OSM segments: %d (%s%% "
                  "of matched features)"
                  % (frag["multi_segment_count"],
                     _fmt(frag["multi_segment_pct_of_matched"])))
    lines.append("Average OSM segments per matched NHA feature: %s"
                  % _fmt(frag["avg_segments_per_matched_feature"], 2))
    lines.append("Maximum OSM segments for a single NHA feature: %d"
                  % frag["max_segments_for_one_feature"])
    lines.append("Overall segment correspondence level: %s (renamed from "
                  "'fragmentation level' - review item #14)" % frag["fragmentation_level"])
    lines.append("Note: a high segment count is EXPECTED OSM editing behaviour "
                  "(roads are split at intersections, admin boundaries, and "
                  "attribute changes) and is not itself evidence of duplicate "
                  "or erroneous OSM geometry. This tool reports segment count "
                  "only; distinguishing legitimate fragmentation from true "
                  "overlapping duplicates would require an additional "
                  "geometry-overlap check between same-road OSM segments, "
                  "which is not currently computed (see Section 13).")
    sections.append(("10. OSM Feature Fragmentation and Representation", lines))

    # ---- 11. Positional Accuracy ----
    lines = []
    lines.append("Tolerance used for %% within tolerance: %s" % pos["tolerance_used"])
    lines.append("Mean distance to nearest OSM feature: %s %s"
                  % (_fmt(pos["mean"]), inv["unit_name"]))
    lines.append("Median distance: %s %s" % (_fmt(pos["median"]), inv["unit_name"]))
    lines.append("Minimum distance: %s %s" % (_fmt(pos["min"]), inv["unit_name"]))
    lines.append("Maximum distance: %s %s" % (_fmt(pos["max"]), inv["unit_name"]))
    lines.append("Features measured: %d" % pos["count_measured"])
    lines.append("%% within tolerance: %s%% (%d of %d)"
                  % (_fmt(pos.get("pct_within_tolerance", 0.0)),
                     pos.get("within_tolerance_count", 0), pos["count_measured"]))
    sections.append(("11. Spatial Accuracy and Positional Deviation", lines))

    # ---- 12. Overall Assessment ----
    lines = []
    lines.append("NHA-OSM Classification Agreement Score (formerly "
                  "'Classification Accuracy Score' - review item #20): %s / 100"
                  % _fmt(overall["classification_score"]))
    lines.append("Spatial Match Score: %s / 100" % _fmt(overall["spatial_score"]))
    lines.append("Geometric Alignment Score: %s / 100" % _fmt(overall["alignment_score"]))
    lines.append("Network Completeness Score: %s / 100" % _fmt(overall["completeness_score"]))
    lines.append("%s Score (formerly 'Perfect Match Score'): %s / 100"
                  % (_label("Perfect Match"), _fmt(overall["perfect_match_score"])))
    lines.append("EXPERIMENTAL/INTERNAL COMPOSITE INDEX: %s / 100"
                  % _fmt(overall["overall_score"]))
    lines.append("INDEX BAND: %s" % overall["rating"])
    lines.append("")
    lines.append("Formula: %s" % overall["formula_note"])
    lines.append("Caution: an equal-weighted average of five conceptually "
                  "different indicators (agreement, overlap, alignment, "
                  "completeness, high-confidence-match rate) is one possible "
                  "summary, not a validated, industry-standard composite "
                  "metric (review item #9); it is labelled here as an "
                  "experimental/internal index rather than a data-quality "
                  "rating (review item #10). Treat the five individual "
                  "scores above, and the underlying Sections 1-11 figures, "
                  "as the PRIMARY findings of this report; the composite "
                  "index and its band are a secondary summary only. This "
                  "dataset combines a high NHA-OSM Classification Agreement "
                  "Score (%s%%) and Network Completeness Score (%s%%) with "
                  "low Spatial Match / %s scores that penalise strict 5 m "
                  "overlap and >=60%% coverage thresholds rather than gross "
                  "positional error - Section 11 shows %s%% of features "
                  "within %s of an OSM feature. See Section 13."
                  % (_fmt(overall["classification_score"]),
                     _fmt(overall["completeness_score"]),
                     _label("Perfect Match"),
                     _fmt(pos.get("pct_within_tolerance", 0.0)),
                     pos["tolerance_used"]))
    sections.append(("12. Overall Classification and Data Quality Assessment", lines))

    # ---- 13. Methodological Notes and Limitations ----
    lines = []
    lines.append("This section documents known methodological limitations "
                  "and open items in this report, so results are read with "
                  "appropriate caution and can be improved in a follow-up "
                  "pass. It does not change any figure reported above.")
    lines.append("")
    lines.append("a) Reference vs. truth: NHA is used here as the AUTHORITATIVE "
                  "reference dataset for classification (Final_Class = "
                  "NHA_Class), but this is a methodological choice, not a "
                  "claim that NHA is error-free. All figures above measure "
                  "OSM's agreement WITH NHA, not absolute correctness of "
                  "either dataset.")
    lines.append("b) Name/route-code matching is supporting evidence only "
                  "(Section A.3.1 in the tool configuration) and can upgrade "
                  "a spatial match's status, but a name/ref match is never "
                  "by itself proof that two features represent the same "
                  "physical road, and a name mismatch does not by itself "
                  "prove they do not.")
    lines.append("c) The Perfect Match definition (Section 5) currently "
                  "combines classification agreement and geometric alignment "
                  "tier only. It does not separately require positional "
                  "deviation below a fixed absolute threshold, confirmed "
                  "route-code identity, or absence of a Match_Count > 1 "
                  "ambiguity; a stricter definition folding in those factors "
                  "would very likely produce a lower Perfect Match count "
                  "than reported.")
    lines.append("d) The 5 / 15 / 50 m alignment tolerances and the 10 m "
                  "positional tolerance are configured constants "
                  "(ALIGNMENT_PERFECT_TOLERANCE etc.) chosen as reasonable "
                  "defaults for this comparison; they are not yet derived "
                  "from documented NHA/OSM positional accuracy specifications "
                  "or source mapping scale, and should be justified or "
                  "re-derived from that source metadata before the tiers are "
                  "used for formal acceptance/rejection decisions.")
    lines.append("e) The Motorway/National-Highway OSM classification "
                  "crosswalk (NHA_OSM_AGREEMENT) - i.e. that OSM Trunk or "
                  "Primary is an acceptable representation of an NHA "
                  "National Highway - reflects general OSM tagging practice "
                  "in Pakistan (motorways are consistently tagged 'motorway'; "
                  "national highways are inconsistently split across "
                  "'trunk'/'primary') but is an editable assumption "
                  "(Section A.3 of the tool) and should be stated as such "
                  "wherever this report's classification figures are cited.")
    lines.append("f) This report is one-directional (NHA -> OSM). It answers "
                  "'how much of the NHA reference network is represented in "
                  "OSM' (Section 8) but cannot compute how many OSM "
                  "Motorway/Trunk/Primary features have NO NHA counterpart, "
                  "or how many are duplicate OSM representations of the same "
                  "road, because X05_Final_Road_Classification is one row "
                  "per NHA feature. A complementary OSM-to-NHA pass is "
                  "needed for a full bidirectional completeness picture.")
    lines.append("g) The OSM comparison universe is the pre-filtered working "
                  "copy (motorway/motorway_link/trunk/trunk_link/primary/"
                  "primary_link only, %d of the full OSM road dataset), so "
                  "all OSM-side figures in this report describe agreement "
                  "within that subset, not the complete OSM road network. "
                  "Link-road subtypes (motorway_link, trunk_link, "
                  "primary_link) are currently folded into their parent "
                  "class (Motorway/Trunk/Primary respectively) rather than "
                  "tracked as a separate category."
                  % inv["osm_total_count"])
    lines.append("h) No visual/manual spot-check of matched, mismatched, and "
                  "unmatched features has been performed as part of this "
                  "automated run; automated spatial/attribute matching can "
                  "produce false matches and false non-matches, so a sample "
                  "review in ArcMap is recommended before the figures above "
                  "are treated as final.")
    lines.append("i) All statistics above are network-wide totals/percentages "
                  "and do not break results out by individual route (e.g. "
                  "per motorway or per national highway) or by geographic "
                  "area. A route-level and/or map-based breakdown would show "
                  "whether mismatches are spread evenly or concentrated in "
                  "specific corridors or regions.")
    lines.append("j) NHA and OSM may have been captured or last edited at "
                  "different times; this report does not record or account "
                  "for the acquisition/edit dates of either input layer, so "
                  "some discrepancies above may reflect legitimate temporal "
                  "change (e.g. a newly built or realigned road) rather than "
                  "a data or matching error.")
    lines.append("k) Feature counts and length-based measures are reported "
                  "separately throughout (e.g. Sections 1, 8 vs 9, 10) "
                  "deliberately, since OSM's segmentation means a single NHA "
                  "road can correspond to a large or small number of OSM "
                  "features independent of how much of its length is "
                  "actually represented; the two measures should continue "
                  "to be read side by side, not interchangeably.")
    sections.append(("13. Methodological Notes and Limitations", lines))

    return sections


# --------------------------------------------------------------------
# Report charts (grouped bar / heatmap / stacked bar / histogram)
# --------------------------------------------------------------------
# Charts are an OPTIONAL enhancement layered on top of the thirteen text
# sections above, exactly like the reportlab PDF itself: matplotlib is
# not guaranteed to be present in every ArcMap 10.8 / Python 2.7
# environment, so chart generation degrades gracefully - if matplotlib
# cannot be imported, the report is still produced in full (PDF or
# text), just without charts, and a single AddWarning explains how to
# enable them. A failure inside any ONE chart function is also caught
# individually so it cannot take down the twelve/thirteen text sections
# or the other six charts.

CHART_DPI = 300

# Consistent color palette used across all five figures (spec: "use a
# consistent visual design ... throughout all figures"). Semantic use is
# fixed: green = strongest/positive correspondence, blue = partial,
# orange = proximate/borderline, red = no correspondence/misaligned,
# gray = not assessable. The same four-color sequence is reused in
# Figures 2, 3 and 5(A) so a reader learns the color meaning once.
COLOR_POSITIVE = "#2E6F40"      # Exact / Full Overlap / High Alignment
COLOR_PARTIAL = "#4F81BD"       # Partial/Similar / Partial Overlap / Slight Deviation
COLOR_PROXIMATE = "#E0932B"     # Spatially Proximate / Significant Deviation
COLOR_NEGATIVE = "#B03A2E"      # No Corresponding Feature / Misaligned
COLOR_NEUTRAL_GRAY = "#8C8C8C"  # Not Assessable
COLOR_PRIMARY_BLUE = "#2C5F8A"  # single-series bars (Figure 1), accent text

# Abbreviations used only for the compact "reference threshold" label in
# Figure 5, Panel B (spec example: "10 m reference threshold") - axis
# labels elsewhere keep the full unit name (e.g. "Meter") for clarity.
LINEAR_UNIT_ABBREVIATIONS = {
    "Meters": "m", "Meter": "m",
    "Feet": "ft", "Foot": "ft",
    "Kilometers": "km", "Kilometer": "km",
    "Miles": "mi", "Mile": "mi",
}

# Maps a section's leading number (as it appears in the "N. Heading"
# strings returned by _build_report_sections) to the figure that belongs
# immediately after that section.
CHART_SECTION_MAP = {
    "1": "fig1",
    "2": "fig2",
    "3": "fig3",
    "6": "fig4",
    "11": "fig5",
}

CHART_TITLES = {
    "fig1": "Figure 1 - NHA Reference Dataset Composition",
    "fig2": "Figure 2 - NHA-OSM Attribute and Name Agreement",
    "fig3": "Figure 3 - Spatial Correspondence Between NHA Reference Roads and OSM",
    "fig4": "Figure 4 - NHA-OSM Road Classification Agreement",
    "fig5": "Figure 5 - Geometric Alignment and Positional Agreement Between NHA and OSM",
}


def _safe_chart(fn, *args):
    """Runs one figure-building function; on any failure, warns and
    returns None rather than aborting the rest of figure generation."""
    try:
        return fn(*args)
    except Exception as e:
        arcpy.AddWarning("  Figure '%s' could not be generated: %s"
                          % (getattr(fn, "__name__", "unknown"), str(e)))
        return None


def _apply_figure_style(plt):
    """
    Applies one shared rcParams profile so all five figures use identical
    typography, sizing, and background - required for the figures to
    read as a single professional series rather than five independently-
    styled charts.
    """
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Liberation Sans", "Helvetica"],
        "font.size": 10,
        "axes.titlesize": 11.5,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 9.5,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.edgecolor": "#333333",
        "axes.linewidth": 0.8,
        "axes.grid": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


# Title-block and footnote spacing is specified in ABSOLUTE INCHES, not
# figure-fraction, and converted to fraction per-figure using that
# figure's actual height (fig.get_figheight()). A fixed fractional gap
# (e.g. 0.045) is the wrong unit here: the same fraction is a smaller
# absolute gap on a shorter figure and a larger one on a taller figure,
# while font size (points) does not change - this was the direct cause
# of the title/subtitle overlap on the shorter (5.5in) bar-chart figures
# versus the excess whitespace on the taller (6.5in) ones. Inches keep
# every figure's spacing visually identical regardless of its figsize.
TITLE_FONTSIZE = 14
SUBTITLE_FONTSIZE = 10.5
EXTRA_LINE_FONTSIZE = 10.5
FOOTNOTE_FONTSIZE = 8.5

TOP_MARGIN_IN = 0.32        # figure top edge -> title baseline
TITLE_TO_NEXT_LINE_IN = 0.36  # title baseline -> subtitle/first extra line
LINE_GAP_IN = 0.30          # gap between subsequent title-block lines
TITLE_BLOCK_BOTTOM_BUFFER_IN = 0.14  # last title-block line -> plot area
FOOTNOTE_BASELINE_IN = 0.30  # figure bottom edge -> footnote baseline
FOOTNOTE_RESERVE_IN = 0.58   # bottom space reserved for a (possibly wrapped) footnote


def _add_title_block(fig, title, subtitle=None, extra_lines=None):
    """
    Places the figure title, an optional italic subtitle, and any extra
    annotation lines as separate fig.text() calls, spaced by a FIXED
    NUMBER OF INCHES (converted per-figure via fig.get_figheight()) so
    spacing is visually identical across all five figures regardless of
    their individual figsize - rather than mixing fig.suptitle with
    ax.set_title, whose auto-computed padding is unpredictable once
    combined with a manual tight_layout rect. Returns the y-coordinate
    (figure fraction) immediately below the last line written, so the
    caller can pass it as the top bound of tight_layout's rect and
    guarantee no collision between the title block and the plot area.
    """
    fig_h = fig.get_figheight()
    y = 1.0 - (TOP_MARGIN_IN / fig_h)
    fig.suptitle(title, fontsize=TITLE_FONTSIZE, fontweight="bold", y=y)
    y -= (TITLE_TO_NEXT_LINE_IN / fig_h)
    if subtitle:
        fig.text(0.5, y, subtitle, ha="center", fontsize=SUBTITLE_FONTSIZE,
                  style="italic", color="#333333")
        y -= (LINE_GAP_IN / fig_h)
    if extra_lines:
        for line, kw in extra_lines:
            fig.text(0.5, y, line, ha="center",
                      fontsize=kw.get("fontsize", EXTRA_LINE_FONTSIZE),
                      fontweight=kw.get("fontweight", "normal"),
                      color=kw.get("color", "#333333"))
            y -= (LINE_GAP_IN / fig_h)
    return y - (TITLE_BLOCK_BOTTOM_BUFFER_IN / fig_h)


def _add_footnote(fig, text):
    """Places a wrapped, italic footnote a fixed number of inches above
    the figure's bottom edge, consistent across all five figures."""
    fig_h = fig.get_figheight()
    y = FOOTNOTE_BASELINE_IN / fig_h
    fig.text(0.5, y, text, ha="center", fontsize=FOOTNOTE_FONTSIZE,
              style="italic", color="#444444", wrap=True)


def _footnote_rect_bottom(fig):
    """Bottom bound (figure fraction) to pass as tight_layout(rect=...)
    so the plot area never encroaches on the footnote reserved below it."""
    return FOOTNOTE_RESERVE_IN / fig.get_figheight()


def _save_figure_all_formats(fig, plt, chart_folder, base_name):
    """
    Saves one figure as PNG (300 DPI, for PDF-report embedding and quick
    viewing), PDF, and SVG (vector, for publication use), all sharing the
    same base_name per the required Figure_0N_... naming convention.
    Returns the PNG path (used to embed the figure in the generated
    report), or None if even the PNG failed to save.
    """
    paths = {}
    for ext in ("png", "pdf", "svg"):
        p = os.path.join(chart_folder, "%s.%s" % (base_name, ext))
        try:
            fig.savefig(p, dpi=CHART_DPI, bbox_inches="tight",
                        facecolor="white")
            paths[ext] = p
        except Exception as e:
            arcpy.AddWarning("  Could not save %s: %s" % (p, str(e)))
    plt.close(fig)
    return paths.get("png")


def generate_report_charts(stats, chart_folder):
    """
    Generates the five required statistical figures as PNG + PDF + SVG
    files in chart_folder, using matplotlib if available in this ArcGIS
    Python environment. Returns {figure_key: png_path} for whichever
    figures were successfully produced (missing keys simply mean that
    figure could not be built - callers must check with .get()).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless backend - no display needed in ArcMap
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        arcpy.AddWarning(
            "Figures were requested but 'matplotlib' is not installed in "
            "this ArcGIS Python environment, so the report will be "
            "generated WITHOUT figures (all thirteen text/PDF sections are "
            "unaffected). To enable figures, install matplotlib ONCE into "
            "ArcGIS's Python 2.7 interpreter (adjust the path to match "
            "your ArcGIS install): "
            "\"C:\\Python27\\ArcGIS10.8\\python.exe\" -m pip install "
            "\"matplotlib==2.2.5\" numpy -- then re-run this tool. "
            "(2.2.5 is the last matplotlib release supporting Python 2.7.)")
        return {}

    if not os.path.exists(chart_folder):
        os.makedirs(chart_folder)

    _apply_figure_style(plt)

    charts = {}
    charts["fig1"] = _safe_chart(
        _figure1_dataset_composition, stats, chart_folder, plt)
    charts["fig2"] = _safe_chart(
        _figure2_attribute_name_agreement, stats, chart_folder, plt)
    charts["fig3"] = _safe_chart(
        _figure3_spatial_correspondence, stats, chart_folder, plt)
    charts["fig4"] = _safe_chart(
        _figure4_classification_agreement, stats, chart_folder, plt, np)
    charts["fig5"] = _safe_chart(
        _figure5_geometric_alignment_positional, stats, chart_folder, plt)

    plt.close("all")
    return dict((k, v) for k, v in charts.items() if v)


def _figure1_dataset_composition(stats, chart_folder, plt):
    """
    FIGURE 1 - NHA Reference Dataset Composition (vertical bar chart).
    Categories: Motorway, National Highway, Strategic Roads, and NHA
    Features Requiring Classification Review - all four NHA_Class
    buckets from Section 1, so the chart reconciles to the same total
    feature count reported there.
    """
    inv = stats["inventory"]
    cats_internal = ["Motorway", "National Highway", "Strategic", "Review"]
    cats_display = ["Motorway", "National Highway", "Strategic Roads",
                     "NHA Features Requiring\nClassification Review"]
    counts = [inv["nha_by_class"].get(c, {"count": 0})["count"]
              for c in cats_internal]

    fig, ax = plt.subplots(figsize=(10, 6.5))
    x = list(range(len(cats_display)))
    bars = ax.bar(x, counts, width=0.55, color=COLOR_PRIMARY_BLUE,
                   edgecolor="white", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(cats_display)
    ax.set_ylabel("Number of NHA Reference Features")
    ax.set_xlabel("NHA Classification Status")
    ymax = max(counts) if counts else 1
    ax.set_ylim(0, ymax * 1.20)
    for b, c in zip(bars, counts):
        ax.annotate(str(int(c)),
                     xy=(b.get_x() + b.get_width() / 2.0, b.get_height()),
                     xytext=(0, 6), textcoords="offset points",
                     ha="center", fontsize=10.5, fontweight="bold")

    top_bound = _add_title_block(
        fig, "NHA Reference Dataset Composition",
        subtitle="Distribution of NHA reference features by classification status")
    _add_footnote(
        fig, "Note: 'NHA Features Requiring Classification Review' is a "
             "classification status, not a formal road class.")
    fig.tight_layout(rect=[0.03, _footnote_rect_bottom(fig), 0.97, top_bound], pad=0.6)
    return _save_figure_all_formats(
        fig, plt, chart_folder, "Figure_01_NHA_Dataset_Composition")


def _figure2_attribute_name_agreement(stats, chart_folder, plt):
    """
    FIGURE 2 - NHA-OSM Attribute and Name Agreement (horizontal bar
    chart, 3 categories per spec). 'No Attribute Match' and 'Unmatched
    (No OSM Feature)' are combined into the single spec-required
    category 'NHA Reference Feature Without Corresponding Attribute/
    Name Match', since both represent the absence of an attribute/name
    correspondence (with or without a spatial candidate present).
    """
    nm = stats["name_match"]
    exact = nm["tally"]["Exact Match"]
    partial = nm["tally"]["Partial/Similar"]
    no_corr = (nm["tally"]["No Attribute Match"] +
               nm["tally"]["Unmatched (No OSM Feature)"])
    total = nm["total"]

    cats = ["Exact Attribute/Name Match",
            "Partial/Similar Attribute/\nName Match",
            "NHA Reference Feature Without\nCorresponding Attribute/Name Match"]
    counts = [exact, partial, no_corr]
    pcts = [100.0 * c / total if total else 0.0 for c in counts]
    colors = [COLOR_POSITIVE, COLOR_PARTIAL, COLOR_NEGATIVE]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    y = list(range(len(cats)))[::-1]
    bars = ax.barh(y, counts, height=0.5, color=colors,
                    edgecolor="white", linewidth=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(cats)
    ax.set_xlabel("Number of NHA Reference Features")
    xmax = max(counts) if counts else 1
    ax.set_xlim(0, xmax * 1.30)
    for b, c, p in zip(bars, counts, pcts):
        ax.annotate("%d (%s%%)" % (c, _fmt(p)),
                     xy=(b.get_width(), b.get_y() + b.get_height() / 2.0),
                     xytext=(8, 0), textcoords="offset points",
                     va="center", fontsize=10.5)

    top_bound = _add_title_block(
        fig, "NHA-OSM Attribute and Name Agreement",
        subtitle=("Attribute/name correspondence among the %d in-scope "
                   "NHA reference features" % total))
    _add_footnote(
        fig, "Note: attribute/name agreement is supporting evidence and "
             "does not by itself establish geographic or geometric "
             "correspondence.")
    fig.tight_layout(rect=[0.03, _footnote_rect_bottom(fig), 0.97, top_bound], pad=0.6)
    return _save_figure_all_formats(
        fig, plt, chart_folder, "Figure_02_NHA_OSM_Attribute_Name_Agreement")


def _figure3_spatial_correspondence(stats, chart_folder, plt):
    """
    FIGURE 3 - Spatial Correspondence Between NHA Reference Roads and
    OSM (horizontal bar chart, 4 categories, strongest-to-weakest order).
    """
    sm = stats["spatial_match"]
    keys = ["Overlapping", "Partially Overlapping",
             "Nearby (Non-overlapping)", "Unmatched"]
    cats = ["Full Spatial Overlap", "Partial Spatial Overlap",
             "Spatially Proximate but\nNon-overlapping",
             "NHA Reference Feature Without\nCorresponding OSM Feature"]
    counts = [sm["tally"][k] for k in keys]
    pcts = [sm["pct"][k] for k in keys]
    colors = [COLOR_POSITIVE, COLOR_PARTIAL, COLOR_PROXIMATE, COLOR_NEGATIVE]

    fig, ax = plt.subplots(figsize=(11, 6))
    y = list(range(len(cats)))[::-1]
    bars = ax.barh(y, counts, height=0.5, color=colors,
                    edgecolor="white", linewidth=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(cats)
    ax.set_xlabel("Number of NHA Reference Features")
    xmax = max(counts) if counts else 1
    ax.set_xlim(0, xmax * 1.30)
    for b, c, p in zip(bars, counts, pcts):
        ax.annotate("%d (%s%%)" % (c, _fmt(p)),
                     xy=(b.get_width(), b.get_y() + b.get_height() / 2.0),
                     xytext=(8, 0), textcoords="offset points",
                     va="center", fontsize=10.5)

    top_bound = _add_title_block(
        fig, "Spatial Correspondence Between NHA Reference Roads and OSM",
        subtitle="Spatial relationship identified using the predefined matching criteria")
    _add_footnote(
        fig, "Note: spatial correspondence and nearest-feature positional "
             "distance represent different measures and should not be "
             "interpreted as equivalent.")
    fig.tight_layout(rect=[0.03, _footnote_rect_bottom(fig), 0.97, top_bound], pad=0.6)
    return _save_figure_all_formats(
        fig, plt, chart_folder, "Figure_03_NHA_OSM_Spatial_Correspondence")


def _figure4_classification_agreement(stats, chart_folder, plt, np):
    """
    FIGURE 4 - NHA-OSM Road Classification Agreement (confusion-matrix
    heatmap). Rows = NHA reference classification, columns = matched OSM
    classification (including a dedicated 'No Corresponding OSM Feature'
    column, never the bare word 'Unmatched'). The overall agreement
    percentage is shown as a small annotation above the matrix, not as
    the title and not repeated inside every cell.
    """
    matrix = stats["class_agreement"]["matrix"]
    nha_classes = [c for c in ("Motorway", "National Highway")
                    if any(k[0] == c for k in matrix.keys())]
    if not nha_classes:
        return None

    osm_seen = sorted(set(k[1] for k in matrix.keys()))
    preferred = ["Motorway", "Trunk", "Primary"]
    no_corr_keys = [c for c in osm_seen if "Unmatched" in c or "None" in c]
    osm_classes = ([c for c in preferred if c in osm_seen] +
                    [c for c in osm_seen
                     if c not in preferred and c not in no_corr_keys] +
                    no_corr_keys)

    osm_display = []
    for c in osm_classes:
        osm_display.append("No Corresponding\nOSM Feature"
                            if c in no_corr_keys else "OSM %s" % c)
    nha_display = ["NHA %s" % c for c in nha_classes]

    data = np.zeros((len(nha_classes), len(osm_classes)))
    for i, nc in enumerate(nha_classes):
        for j, oc in enumerate(osm_classes):
            data[i, j] = matrix.get((nc, oc), 0)

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    im = ax.imshow(data, cmap="Blues", aspect="auto", vmin=0)
    ax.set_xticks(list(range(len(osm_display))))
    ax.set_xticklabels(osm_display, fontsize=10)
    ax.set_yticks(list(range(len(nha_display))))
    ax.set_yticklabels(nha_display, fontsize=10)
    ax.set_xlabel("OSM Classification")
    ax.set_ylabel("NHA Reference Classification")

    vmax = data.max() if data.max() > 0 else 1.0
    for i in range(len(nha_classes)):
        for j in range(len(osm_classes)):
            val = int(data[i, j])
            text_color = "white" if data[i, j] > vmax * 0.55 else "#1a1a1a"
            ax.text(j, i, str(val), ha="center", va="center",
                     color=text_color, fontsize=12.5, fontweight="bold")
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.06)
    cbar.set_label("Number of NHA Reference Features", fontsize=9.5)

    ca = stats["class_agreement"]
    overall_total = ca["motorway_total"] + ca["nh_total"]
    overall_correct = ca["motorway_correct"] + ca["nh_correct"]
    overall_pct = (100.0 * overall_correct / overall_total) if overall_total else 0.0

    top_bound = _add_title_block(
        fig, "NHA-OSM Road Classification Agreement",
        subtitle="Feature-level correspondence between NHA reference and OSM road classifications",
        extra_lines=[("Overall classification agreement: %s%%" % _fmt(overall_pct),
                        {"fontsize": 10.5, "fontweight": "bold",
                         "color": COLOR_PRIMARY_BLUE})])
    _add_footnote(
        fig, "Note: rows represent the NHA reference classification; "
             "columns represent the corresponding OSM classification.")
    fig.tight_layout(rect=[0.03, _footnote_rect_bottom(fig), 0.97, top_bound], pad=0.6)
    return _save_figure_all_formats(
        fig, plt, chart_folder, "Figure_04_NHA_OSM_Classification_Agreement")


def _figure5_geometric_alignment_positional(stats, chart_folder, plt):
    """
    FIGURE 5 - Geometric Alignment and Positional Agreement Between NHA
    and OSM (two-panel figure, treated as one final figure per spec).
    Panel A: horizontal bar of alignment tiers (High Alignment / Slight
    Deviation / Significant Deviation / Misaligned, plus 'Not Assessable'
    appended only if the dataset actually contains such features, so no
    real data is dropped from the chart). Panel B: histogram of
    NHA-OSM positional distances with the matching-tolerance threshold
    marked as a vertical reference line.
    """
    al = stats["alignment"]
    pos = stats["positional"]
    distances = pos.get("distances", [])

    keys = ["Perfect", "Slight Deviation", "Significant Deviation", "Misaligned"]
    display = ["High Alignment", "Slight Deviation", "Significant Deviation", "Misaligned"]
    colors = [COLOR_POSITIVE, COLOR_PARTIAL, COLOR_PROXIMATE, COLOR_NEGATIVE]
    counts = [al["tally"][k] for k in keys]
    pcts = [al["pct"][k] for k in keys]
    na_count = al["tally"].get("Not Assessable", 0)
    if na_count:
        display.append("Not Assessable")
        counts.append(na_count)
        pcts.append(al["pct"].get("Not Assessable", 0.0))
        colors.append(COLOR_NEUTRAL_GRAY)

    fig, (axA, axB) = plt.subplots(1, 2, figsize=(15.5, 6.5))

    yA = list(range(len(display)))[::-1]
    barsA = axA.barh(yA, counts, height=0.55, color=colors,
                       edgecolor="white", linewidth=0.6)
    axA.set_yticks(yA)
    axA.set_yticklabels(display, fontsize=10)
    axA.set_xlabel("Number of NHA Reference Features")
    xmax = max(counts) if counts else 1
    axA.set_xlim(0, xmax * 1.38)
    for b, c, p in zip(barsA, counts, pcts):
        axA.annotate("%d (%s%%)" % (c, _fmt(p)),
                      xy=(b.get_width(), b.get_y() + b.get_height() / 2.0),
                      xytext=(6, 0), textcoords="offset points",
                      va="center", fontsize=9.5)
    axA.set_title("A. Geometric Alignment Categories", fontsize=12,
                   fontweight="bold", pad=12)

    if distances:
        tol_value_m, tol_unit = _parse_linear_unit(pos["tolerance_used"])
        axB.hist(distances, bins=24, color=COLOR_PARTIAL,
                  edgecolor="white", linewidth=0.5)
        axB.axvline(tol_value_m, color=COLOR_NEGATIVE, linestyle="--",
                     linewidth=1.6)
        ymax_b = axB.get_ylim()[1]
        unit_abbrev = LINEAR_UNIT_ABBREVIATIONS.get(tol_unit, tol_unit)
        threshold_label = "%s %s reference threshold" % (_fmt(tol_value_m, 0), unit_abbrev)
        axB.annotate(threshold_label,
                      xy=(tol_value_m, ymax_b * 0.96),
                      xytext=(8, -4), textcoords="offset points",
                      fontsize=9, color=COLOR_NEGATIVE, va="top")
    else:
        axB.text(0.5, 0.5, "No positional distance data available",
                  ha="center", va="center", transform=axB.transAxes,
                  fontsize=10, style="italic")
    axB.set_xlabel("NHA-OSM Positional Distance (%s)"
                    % stats["inventory"]["unit_name"])
    axB.set_ylabel("Number of Assessed Features")
    axB.set_title("B. Positional Distance Distribution", fontsize=12,
                   fontweight="bold", pad=12)

    top_bound = _add_title_block(
        fig, "Geometric Alignment and Positional Agreement Between NHA and OSM")
    _add_footnote(
        fig, "Note: alignment categories are based on the predefined "
             "positional tolerance and percentage-of-road-length "
             "criteria; positional distance represents proximity and "
             "should not be interpreted as complete geometric overlap.")
    fig.tight_layout(rect=[0.02, _footnote_rect_bottom(fig), 0.98, top_bound], pad=0.6, w_pad=4.0)
    return _save_figure_all_formats(
        fig, plt, chart_folder,
        "Figure_05_Geometric_Alignment_Positional_Agreement")


def write_statistical_report_pdf(stats, report_folder, workspace):
    """
    Writes the full thirteen-section report as a formatted PDF using
    reportlab (reportlab.platypus). reportlab is NOT part of the ArcMap
    10.8 / Python 2.7 standard installation - it must be installed once
    into ArcGIS's bundled Python interpreter, e.g.:

        "C:\\Python27\\ArcGIS10.8\\python.exe" -m pip install reportlab

    This is a normal, supported, one-time setup step used widely for
    ArcMap automation (reportlab is pure-Python and has no compiled
    dependencies, so it installs cleanly on locked-down machines).

    FALLBACK: if reportlab is not installed, this function does NOT
    crash the whole toolbox run. It instead writes the identical report
    content as a plain-text (.txt) file and raises a clear AddWarning
    explaining exactly how to enable PDF output, so classification and
    matching results are never lost just because the report step lacks
    a dependency.
    """
    if not os.path.exists(report_folder):
        os.makedirs(report_folder)

    sections = _build_report_sections(stats, workspace)
    overall = stats["overall"]

    arcpy.AddMessage("  Generating report figures...")
    charts = generate_report_charts(
        stats, os.path.join(report_folder, "charts"))
    if charts:
        arcpy.AddMessage("  %d of 5 figures generated (PNG/PDF/SVG saved "
                          "under %s)."
                          % (len(charts), os.path.join(report_folder, "charts")))

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib import colors
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, PageBreak, Image)
    except ImportError:
        # ---- Fallback: plain text report, never fail the whole run ----
        report_path = os.path.join(
            report_folder, "Final_Statistical_Summary_NHA_vs_OSM.txt")
        lines = []
        lines.append("=" * 78)
        lines.append("FINAL STATISTICAL SUMMARY - NHA REFERENCE vs OSM")
        lines.append("Survey of Pakistan - Road Features Classification Project")
        lines.append("Source geodatabase: %s" % workspace)
        lines.append("=" * 78)
        lines.append("")
        for heading, body_lines in sections:
            lines.append("-" * 78)
            lines.append(heading.upper())
            lines.append("-" * 78)
            lines.extend(body_lines)
            section_num = heading.split(".")[0].strip()
            chart_key = CHART_SECTION_MAP.get(section_num)
            if chart_key and charts.get(chart_key):
                png_path = charts[chart_key]
                base_noext = os.path.splitext(png_path)[0]
                lines.append("[%s -- saved as PNG/PDF/SVG: %s.(png|pdf|svg)]"
                              % (CHART_TITLES.get(chart_key, chart_key),
                                 base_noext))
            lines.append("")
        lines.append("=" * 78)
        lines.append("END OF REPORT")
        lines.append("=" * 78)
        # Write as UTF-8 explicitly (review/bugfix: do not rely on
        # Python 2's default 'ascii' codec here - NHA/OSM Name values can
        # contain non-ASCII characters such as en-dashes or Urdu script,
        # and a plain open(path, "w").write(unicode_text) call implicitly
        # encodes to ASCII and crashes on the first such character).
        report_text = u"\n".join(_safe_unicode(l) for l in lines)
        with io.open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)

        arcpy.AddWarning(
            "PDF report requested but the 'reportlab' Python package is "
            "not installed in this ArcGIS Python environment, so a plain "
            "text report was written instead: %s. To enable PDF output, "
            "install reportlab ONCE into ArcGIS's Python 2.7 interpreter "
            "by running this from an elevated Command Prompt (adjust the "
            "path to match your ArcGIS install): "
            "\"C:\\Python27\\ArcGIS10.8\\python.exe\" -m pip install "
            "reportlab -- then re-run this tool." % report_path)
        return report_path

    # ---- reportlab available: build the real PDF ----
    report_path = os.path.join(
        report_folder, "Final_Statistical_Summary_NHA_vs_OSM.pdf")

    doc = SimpleDocTemplate(
        report_path, pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm,
        topMargin=2.0 * cm, bottomMargin=2.0 * cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=16, spaceAfter=6)
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontSize=10,
        alignment=TA_CENTER, textColor=colors.grey, spaceAfter=4)
    heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], fontSize=12,
        spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1a3d6d"))
    body_style = ParagraphStyle(
        "ReportBody", parent=styles["Normal"], fontSize=9.5, leading=13)
    score_style = ParagraphStyle(
        "ScoreLine", parent=styles["Normal"], fontSize=11, leading=15)

    story = []
    story.append(Paragraph(
        "Final Statistical Summary &ndash; NHA Reference vs OSM", title_style))
    story.append(Paragraph(
        "Survey of Pakistan &ndash; Road Features Classification Project",
        subtitle_style))
    story.append(Paragraph("Source geodatabase: %s" % _safe_unicode(workspace), subtitle_style))
    story.append(Spacer(1, 10))

    # Executive summary box (Requirement 12 headline, shown up-front for
    # readability, with full detail repeated in section 12 below).
    exec_data = [
        ["Overall Quality Score", "%s / 100" % _fmt(overall["overall_score"])],
        ["Overall Rating", overall["rating"]],
    ]
    exec_table = Table(exec_data, colWidths=[8 * cm, 6 * cm])
    exec_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef3fa")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#a9bcd6")),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(exec_table)
    story.append(Spacer(1, 8))

    for heading, body_lines in sections:
        story.append(Paragraph(_safe_unicode(heading), heading_style))
        for line in body_lines:
            if line == "":
                story.append(Spacer(1, 4))
                continue
            # Coerce to unicode first (line may contain non-ASCII Name/ref
            # values pulled from the geodatabase - see _safe_unicode()),
            # THEN escape characters that would be misread as XML markup
            # by reportlab's Paragraph parser (only & < > are special).
            safe_line = (_safe_unicode(line).replace(u"&", u"&amp;")
                             .replace(u"<", u"&lt;")
                             .replace(u">", u"&gt;"))
            story.append(Paragraph(safe_line, body_style))

        section_num = heading.split(".")[0].strip()
        chart_key = CHART_SECTION_MAP.get(section_num)
        if chart_key and charts.get(chart_key):
            chart_path = charts[chart_key]
            try:
                # Scale the PNG proportionally to a fixed page width using
                # reportlab's own ImageReader (always available - no extra
                # dependency like Pillow needed just to read image size).
                img_reader = ImageReader(chart_path)
                native_w, native_h = img_reader.getSize()
                target_w = 15.5 * cm
                target_h = target_w * (float(native_h) / float(native_w))
                story.append(Spacer(1, 4))
                story.append(Image(chart_path, width=target_w, height=target_h))
                story.append(Spacer(1, 6))
            except Exception as e:
                arcpy.AddWarning("  Could not embed chart '%s' in the PDF: %s"
                                  % (chart_key, str(e)))

    doc.build(story)

    return report_path


def write_supporting_tables(stats, workspace):
    """
    Writes small geodatabase tables backing the key report sections so
    every headline figure is independently auditable in ArcMap without
    re-running the analysis. One table per major section that has
    per-feature detail rows available.
    """
    # Requirement 2: Name/Attribute matching detail
    tbl_name = os.path.join(workspace, "Stat_NameAttributeMatch")
    if arcpy.Exists(tbl_name):
        arcpy.Delete_management(tbl_name)
    arcpy.CreateTable_management(workspace, "Stat_NameAttributeMatch")
    arcpy.AddField_management(tbl_name, "NHA_Src_OID", "LONG")
    arcpy.AddField_management(tbl_name, "NHA_Name", "TEXT", field_length=150)
    arcpy.AddField_management(tbl_name, "NHA_Class", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_name, "Match_Status", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_name, "OSM_Match_ID", "LONG")
    arcpy.AddField_management(tbl_name, "OSM_Class", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_name, "Attribute_Category", "TEXT", field_length=30)
    # Road_Type / Road_Name (project requirement: name every road in the
    # final layer by combining NHA with its matched OSM feature) mirror
    # X05_Final_Road_Classification exactly - see compute_name_attribute_
    # matching()'s docstring for why these are read from the final layer
    # rather than recomputed here.
    arcpy.AddField_management(tbl_name, "Road_Type", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_name, "Road_Name", "TEXT", field_length=300)
    with arcpy.da.InsertCursor(
            tbl_name, ["NHA_Src_OID", "NHA_Name", "NHA_Class", "Match_Status",
                       "OSM_Match_ID", "OSM_Class", "Attribute_Category",
                       "Road_Type", "Road_Name"]) as cur:
        for row in stats["name_match"]["detail_rows"]:
            cur.insertRow(row)

    # Requirement 3: Spatial tier detail
    tbl_spatial = os.path.join(workspace, "Stat_SpatialMatchTiers")
    if arcpy.Exists(tbl_spatial):
        arcpy.Delete_management(tbl_spatial)
    arcpy.CreateTable_management(workspace, "Stat_SpatialMatchTiers")
    arcpy.AddField_management(tbl_spatial, "NHA_Src_OID", "LONG")
    arcpy.AddField_management(tbl_spatial, "Spatial_Tier", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_spatial, "Coincidence_Pct", "DOUBLE")
    with arcpy.da.InsertCursor(
            tbl_spatial, ["NHA_Src_OID", "Spatial_Tier", "Coincidence_Pct"]) as cur:
        for row in stats["spatial_match"]["detail_rows"]:
            cur.insertRow(row)

    # Requirement 4: Alignment detail
    tbl_align = os.path.join(workspace, "Stat_GeometricAlignment")
    if arcpy.Exists(tbl_align):
        arcpy.Delete_management(tbl_align)
    arcpy.CreateTable_management(workspace, "Stat_GeometricAlignment")
    arcpy.AddField_management(tbl_align, "NHA_Src_OID", "LONG")
    arcpy.AddField_management(tbl_align, "Alignment_Tier", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_align, "Best_Coverage_Pct", "DOUBLE")
    with arcpy.da.InsertCursor(
            tbl_align, ["NHA_Src_OID", "Alignment_Tier", "Best_Coverage_Pct"]) as cur:
        for row in stats["alignment"]["detail_rows"]:
            cur.insertRow(row)

    # Requirement 6: Classification confusion matrix
    tbl_matrix = os.path.join(workspace, "Stat_ClassificationMatrix")
    if arcpy.Exists(tbl_matrix):
        arcpy.Delete_management(tbl_matrix)
    arcpy.CreateTable_management(workspace, "Stat_ClassificationMatrix")
    arcpy.AddField_management(tbl_matrix, "NHA_Class", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_matrix, "OSM_Class", "TEXT", field_length=30)
    arcpy.AddField_management(tbl_matrix, "Count", "LONG")
    with arcpy.da.InsertCursor(
            tbl_matrix, ["NHA_Class", "OSM_Class", "Count"]) as cur:
        for (nha_class, osm_class), cnt in stats["class_agreement"]["matrix"].items():
            cur.insertRow((nha_class, osm_class, cnt))

    arcpy.AddMessage("  Supporting tables written: Stat_NameAttributeMatch, "
                      "Stat_SpatialMatchTiers, Stat_GeometricAlignment, "
                      "Stat_ClassificationMatrix.")
    return

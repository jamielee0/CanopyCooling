"""Copy public support artifacts and describe schema without reading effects."""
import json
import shutil
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
PUB=ROOT/"outputs/v6_2/scientific/spatial_scale_review_20261004"
OUT=ROOT/"deliverables/Spatial_Scale_Review_2023_v6_2_20261004"


def describe(name):
    identity={"city":"Frozen pilot city", "orbit":"Acquisition orbit, identifier text", "date":"Acquisition date in 2023, YYYY-MM-DD", "source_run_id":"Original cached frame/model run identity", "source":"Historical source table path"}
    if name in identity:return "identifier or ISO date",identity[name],"never missing"
    if name.startswith("q") and name[1:].isdigit():return "same unit as variable",f"Cell-weighted quantile at probability {int(name[1:])/100:g}; q00=min, q100=max","blank only for an empty population"
    if name in ("mean","sd"):return "same unit as variable","Cell-weighted predictor mean" if name=="mean" else "Sample SD of predictor values, ddof=1","blank for empty population; SD also blank if fewer than two cells"
    if name in ("variable","unit","population","n"):
        return "field name, unit, population or count",{"variable":"One of canopy_fraction and six frozen controls", "unit":"fraction or m", "population":"original / retained_all11 / excluded_from_all11; no support cutoff", "n":"Number of unique native-cell observations contributing to the predictor distribution"}[name],"never missing"
    info={"maximum_block_information_share":"Largest residualized canopy-information share of a block", "top_five_block_information_share":"Sum of the five largest residualized block-information shares", "effective_information_blocks":"Inverse sum of squared residualized information shares; not actual independent blocks", "maximum_slope_design_leverage":"Published maximum single-cell slope-design leverage", "within_block_canopy_variance":"Block-demeaned canopy Sxx divided by cell count", "residualized_canopy_Sxx":"Canopy information after block intercepts and context adjustment"}
    for prefix in ("original_","common_"):
        if name.startswith(prefix) and name[len(prefix):] in info:
            field=name[len(prefix):]
            unit="effective blocks" if field=="effective_information_blocks" else "fraction²" if field in ("within_block_canopy_variance","residualized_canopy_Sxx") else "fraction"
            return unit, prefix[:-1]+" population: "+info[field],"common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION"
    definitions={
        "kind":("category","Constituent original/common/registration precision, fresh joint common-minus-original difference, or validated archived fixed-support difference"),
        "variant":("label","Explicit fit or uncertainty configuration; do not treat variants as independent acquisitions"),
        "group_km":("km","Whole spatial-group side length; mean models retain 1km block intercepts"),
        "n_cells":("cells","Constituent fit sample; for joint difference, common sample size—original size is in support table"),
        "n_blocks":("blocks","Constituent fit blocks; for joint difference, common 1km blocks"),
        "groups":("groups","Resampling groups; joint differences use union of occupied original/common physical groups"),
        "bootstrap_requested":("draws","Requested existing or fresh resampling draws"),
        "bootstrap_estimable":("draws","Draws estimable jointly in both model spaces and, for joint difference, both populations"),
        "bootstrap_failed":("draws","Requested minus estimable draws; no pass selection to rescue nonestimability"),
        "T_SE_K_per_10pp":("K/+10pp","Sample SD of temperature cooling or specified paired cooling-difference draws"),
        "T_width95_K_per_10pp":("K/+10pp","95% percentile interval width; no point or endpoints disclosed"),
        "M_SE_W_m2_per_10pp":("W/m²/+10pp","Sample SD of matched emitted-flux change/difference draws; precision only"),
        "M_width95_W_m2_per_10pp":("W/m²/+10pp","Matched flux 95% interval width; point and endpoints remain sealed"),
        "interval_method":("method","Existing constituent/matched or new joint whole-block percentile bootstrap; labelled explicitly"),
        "pairing_status":("status","What is proven about physical sample and draw correspondence; constituent intervals do not establish difference intervals"),
        "effect_status":("status","SEALED_USER_REQUEST on every precision row"),
        "original_cells":("cells","Original retained paired native-cell population for the pass"),
        "original_blocks":("blocks","Occupied original 1km intercept blocks"),
        "reference_f0":("canopy fraction","Historical fixed lower endpoint; not reselected to optimize results"),
        "reference_f1":("canopy fraction","Historical f0+0.10 endpoint"),
        "reference_cells":("cells","All original cells in blocks whose observed canopy min/max cover both frozen endpoints"),
        "reference_supporting_blocks":("blocks","Number of blocks whose observed raw canopy range covers both endpoints"),
        "reference_status":("status","SUPPORTED or NOT_SUPPORTED_NO_REFERENCE_BLOCKS; no minimum replacement count"),
        "common_all11_cells":("cells","Exact unique native-cell intersection over all11 Phoenix passes"),
        "common_all11_blocks":("blocks","Occupied original 1km block identities in the common sample"),
        "common_all11_area_km2":("km²","Sum of common unique whole 70m cells in Phoenix UTM12: cells×0.0049; not city-clipped area"),
        "common_all11_retained_fraction":("fraction","Common cells divided by this pass's original cells"),
        "excluded_cells":("cells","Original cells outside the all11 intersection; original minus common"),
        "common_scope":("status","Phoenix intersection only; Atlanta fields marked NOT_APPLICABLE_PHOENIX_INTERSECTION"),
        "boundary_km":("km","Historical 1km/2km group-boundary residual-neighbor diagnostic"),
        "cross_boundary_neighbor_pairs":("pairs","Historical cardinal native-neighbor pairs crossing the specified group boundary"),
        "interpretation":("text","Historical diagnostic warning: correlation is neither a p-value nor an effect sign"),
        "LST_K_residual_cross_boundary_correlation":("correlation","Inherited temperature residual correlation across neighboring cells at group boundaries"),
        "M_W_m2_residual_cross_boundary_correlation":("correlation","Inherited emitted-flux residual neighbor correlation"),
    }
    if name not in definitions:raise ValueError("Undocumented public column: "+name)
    unit, definition=definitions[name]
    missing="common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION" if name.startswith("common_all11") or name=="excluded_cells" else "precision blank only if NOT_ESTIMABLE; never substitute zero" if "_SE_" in name or "width95" in name else "never missing"
    return unit,definition,missing


def assemble():
    data=json.loads((PUB/"public_table_matrices.json").read_text())
    dictionary={"missing_encoding":"empty CSV cell is missing/not applicable, never zero", "new_effect_values":"withheld at user's explicit request", "tables":{}}
    text=["# Spatial review public table dictionary", "", "All four tables contain nonthermal support or precision diagnostics. New effect points, signs and interval endpoints are absent. The private comparison figures and arrays remain sealed. Counts across uncertainty variants or repeated common-cell distributions are not independent observations.", ""]
    for name, table in data.items():
        definitions=[]
        text += ["## "+name, "", "| Column | Unit | Meaning | Missing rule |", "| --- | --- | --- | --- |"]
        for header in table["headers"]:
            unit, definition, missing=describe(header)
            definitions.append(dict(column=header, unit=unit, definition=definition, missing=missing))
            text.append(f"| `{header}` | {unit} | {definition} | {missing} |")
        text += [""]
        dictionary["tables"][name]=definitions
    (OUT/"data_dictionary.md").write_text("\n".join(text)+"\n")
    (OUT/"data_dictionary.json").write_text(json.dumps(dictionary,indent=2)+"\n")
    for stem in ("common_footprint_predictor_map", "common_footprint_retention", "retained_excluded_predictor_distributions"):
        for extension in ("png","pdf"):shutil.copy2(PUB/f"{stem}.{extension}",OUT/f"{stem}.{extension}")
    for name in ("validation.json","sealed_figure_qa_metadata.json"):shutil.copy2(PUB/name,OUT/name)
    support=data["footprint_and_reference_support.csv"]
    records=[dict(zip(support["headers"],row)) for row in support["rows"]]
    phoenix=[r for r in records if r["city"]=="phoenix"]
    summary=dict(main_pilot={"Phoenix":11,"Atlanta":5,"year":2023}, common_cells=196090, common_area_km2=960.841,
        retained_fraction_range=[min(r["common_all11_retained_fraction"] for r in phoenix),max(r["common_all11_retained_fraction"] for r in phoenix)],
        reference_support_status=dict(Counter(r["reference_status"] for r in records)),
        joint_difference_intervals="computed internally using union-block draws; all new effects remain sealed",
        fixed_registration="24 paired differences validated", available_registration="44 points, no unsupported paired difference interval",
        raw_model_or_time_files_disclosed=False, scale_ruling="not made", tolerance=None)
    distributions=data["canopy_context_distributions.csv"]
    d=[dict(zip(distributions["headers"],row)) for row in distributions["rows"]]
    summary["canopy_medians"]={p:[min(r["q50"] for r in d if r["population"]==p and r["variable"]=="canopy_fraction"), max(r["q50"] for r in d if r["population"]==p and r["variable"]=="canopy_fraction")] for p in ("original","retained_all11","excluded_from_all11")}
    (OUT/"nonthermal_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (OUT/"remaining_limits.json").write_text(json.dumps(dict(
        new_effect_display="deferred at user's explicit request; Reza tolerance pending", sealed_figure_visual_review="deferred; metadata/nonblank checks only",
        available_support_registration_difference_intervals="unavailable: differing or unverified paired cell samples; separate constituent intervals stored privately",
        inherited_residual_neighbor_diagnostics="10 original passes only; not recomputed for six Phoenix additions",
        reference_applicability="historical f0/f1/Tref/emissivity held fixed; all16 raw endpoint-support counts audited without reselection",
        geometry_weather="Step2 missingness/25-degree/azimuth exceptions remain; not resolved by registration or common cells",
        temporal_inference="no time model or empirical day/window comparison performed", scientific_agreement_cutoff=None,
        further_city_screening_or_thermal_expansion="paused pending results review and separate scope decision"),indent=2)+"\n")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":assemble()

"""Record the authorized Step 5 computation while preserving historical decisions."""
import copy
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT/"src"))
from v6_2_advance.run_quadratic_sensitivity import RUN, EXEC, PACKET, ACTIVE_DOCS, public, sha, write

ARCHIVE = ROOT/"docs/v2/v6_2/archive/before_quadratic_step5_20261005"
TAG = "step5_quadratic_sensitivity_20261005"


class UniqueLoader(yaml.SafeLoader): pass


def mapping(loader, node, deep=False):
    loader.flatten_mapping(node); result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result: raise ValueError("Duplicate YAML key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def main():
    completion = json.loads(public("completion.json").read_text())
    verification = json.loads((EXEC/"verification.json").read_text())
    if completion["passes"] != 16 or verification["status"] != "PASS": raise ValueError("Incomplete execution")
    for rel in ACTIVE_DOCS:
        if sha(ROOT/rel) != sha(ARCHIVE/rel): raise ValueError("Active document changed since snapshot")
    old_protocol = yaml.load((ARCHIVE/"docs/v2/v6_2/protocol_v6_2.yml").read_text(), Loader=UniqueLoader)
    statement = ("The 5 October 2026 continuation explicitly authorizes the remaining Step 5 internal quadratic fitting, "
        "resolving the prior scope question and superseding only the Step4 quadratic-fitting hold. Internal computation is complete in "
        "`docs/v2/v6_2/execution/quadratic_step5_20261005/`, with the public support/precision packet in "
        "`deliverables/Step5_Quadratic_2023_v6_2_20261005/`. All sixteen paired quadratic fits and all32,000 matched 1km/8km draws are estimable; "
        "sixteen original linear temperature estimates are recovered. Native samples and all six controls remain unchanged. "
        "Finite contrasts, matched changes and 32 curve figures are stored sealed. Effect display, empirical effect-figure visual review and "
        "scientific interpretation remain deferred. The authorized fitting component is complete; full Step5 effect review is not complete. "
        "No log/higher-degree model search, reference reselection, support cutoff, city ranking, new time inference, scale ruling or expansion is authorized by this step. "
        "Reza's tolerance remains pending and the explicit sealing instruction stays in force.")
    p = ROOT/"AGENTS.md"; text = p.read_text(); text = text.replace("## Scope and preservation", statement+"\n\n## Scope and preservation", 1); p.write_text(text)
    p = ROOT/"docs/v2/v6_2/pilot_plan_v6_2.md"; text = p.read_text(); pos = text.index("\n")
    text = text[:pos+1]+"\n## Current Step 5 status — 5 October 2026\n\n"+statement+"\n\nEarlier dated entries below are preserved execution history; the current entry resolves their pending fitting scope.\n"+text[pos+1:]; p.write_text(text)
    p = ROOT/"docs/v2/v6_2/results_review_and_targeted_analysis_plan_20260930.md"; text = p.read_text()
    old = "Current status: Steps 1–2, Step 3 internal/support work, the provisional Step 4 review and Step5 predictor-only support/design audit are complete. Step5 empirical fitting scope is pending clarification; effect-based Stage1 review remains deferred under the user's sealing instruction."
    new = "Current status (5 October 2026): Steps 1–2, Step 3 internal/support work, the provisional Step 4 review, and Step5 support audit plus internal quadratic fitting are complete. New quadratic effects and comparisons remain sealed; full Step5 visual/scientific effect review and effect-based Stage1 review remain deferred. The current continuation resolves the earlier fitting-scope question."
    if text.count(old) != 1: raise ValueError("Plan status anchor changed")
    text = text.replace(old, new)
    start = text.index("**Predictor-only audit completed 4 October 2026; empirical fitting scope pending.**")
    end = text.index("\n\n", start)
    text = text[:start]+"**Support audit and internal fitting complete, 5 October 2026; effect review remains sealed.** "+statement+text[end:]
    p.write_text(text)
    entry = "\n\n### 5 October 2026 — Step 5 quadratic fitting completed internally\n\n"+statement+"\n\n"
    entry += ("The user requested ‘ok lets do that part of part 5? Is part 5 fully done yet?’ after the quadratic-versus-alternative discussion. "
        "Treat this as authorization for the previously specified quadratic sensitivity, not a new model-selection search. Freeze the existing fifteen candidate pairs, "
        "three neighbourhood widths, historical thermal reference, full original populations, raw-square centring and protected terms before outcome access. "
        "Reuse the predictor audit's physical resampling sequences; verify all32 draw hashes rather than relying on a shared seed. "
        "The 158 block-spanned candidate pass/pairs receive finite contrasts, and 82 unspanned pairs are explicitly unestimated. "
        "This is descriptive range support without a conditional-overlap or adequacy ruling. All prior figures, samples, controls and access records are preserved.\n\n"
        "Twelve known-answer/boundary tests and programmatic checks pass. All21 frozen inputs and eight source-code hashes reconcile. "
        "A public precision figure and a synthetic comparison template were visually checked; the 32 new empirical comparison figures were checked only "
        "for decoding, dimensions, nonblank content, hashes and private permissions. Public serialization excludes effects, endpoints and significance indicators. "
        "The historical automatic scale-promotion rule was not used. Active documents were archived with checksums before amendment. "
        "No external communication, commit, push, new acquisition or time analysis occurred.\n")
    p = ROOT/"docs/v2/v6_2/decision_log_v6_2.md"; p.write_text(p.read_text()+entry)
    p = ROOT/"docs/v2/v6_2/prior_thermal_access.md"
    p.write_text(p.read_text()+"\n\n### 5 October 2026 — authorized internal quadratic sensitivity\n\n"
        "The latest user explicitly requested the remaining Step5 component. Code decoded paired LST, emitted-energy and emissivity columns from the sixteen "
        "unchanged cached 2023 native frames, fitted sixteen paired quadratic models, reconstructed sixteen linear models and computed 32,000 matched whole-group draws. "
        "The prior released LST table was read to verify exact linear recovery. New coefficients, bootstrap arrays, finite contrasts, paired model differences, "
        "diagnostic equivalents and curve images were stored in `outputs/v6_2/sealed_coefficients/quadratic_step5_20261005/`. Programmatic verification read only these "
        "new sealed outputs; no pre-existing sealed effect file or empirical time contrast was opened. No new raw thermal raster was read. "
        "New effects, interval endpoints, signs and significance were neither displayed nor inspected by the assistant or user. "
        "Only completion/support/precision records and a public precision figure were reviewed; a separately labelled synthetic image checked the effect-figure layout. "
        "Reza's tolerance is still unset. This is exploratory after prior effect disclosure and does not establish global outcome blindness or professor approval. "
        "Scope, input/output identities and access columns are recorded in `execution/quadratic_step5_20261005/`.\n")
    section = dict(authority="2026-10-05 user explicitly requests remaining Step5 component; internal fitting authorized, new effects remain sealed",
        status=completion["status"], supersedes="Step4 quadratic fitting hold and Step5 fitting-scope question only",
        execution_freeze="docs/v2/v6_2/execution/quadratic_step5_20261005/execution_freeze.json",
        packet="deliverables/Step5_Quadratic_2023_v6_2_20261005/README.md", year=2023,
        Phoenix_passes=11, Atlanta_passes=5, other_year_weight=0, native_cell_pass_observations=7511083,
        paired_quadratic_fits=16, reconstructed_linear_fits=16, all_original_linear_LST_points_recovered=True,
        retained_controls=6, raw_f_squared_before_block_centering=True, protected_canopy_terms=2,
        groups_km=[1,8], configurations=32, replicates_each=1000, paired_draws_estimable=32000, paired_draws_failed=0,
        audited_draw_hashes_reconciled=32, candidate_pairs=15, block_spanned_candidate_pass_pairs=158,
        unspanned_candidate_pass_pairs_not_estimated=82, reference_reselection=False, new_support_inclusion_cutoff=None,
        empirical_effect_figures_rendered=32, empirical_effect_figures_visually_reviewed=False,
        public_precision_figure_visually_reviewed=True, new_effect_display=False,
        authorized_computational_component_complete=True, full_Step5_effect_review_complete=False,
        primary_estimator_replaced=False, model_selection_search=False, new_time_inference=False,
        scale_tolerance=None, scale_ruling=None, additional_city_or_year_processing=False,
        known_answer_tests_passed=12, input_hashes_verified=21)
    p = ROOT/"docs/v2/v6_2/protocol_v6_2.yml"; text = p.read_text()
    changes = {
        "updated_on: '2026-10-04'":"updated_on: '2026-10-05'",
        "status: STEP5_PREDICTOR_AUDIT_COMPLETE_QUADRATIC_FITTING_SCOPE_PENDING_2023":"status: STEP5_INTERNAL_QUADRATIC_COMPLETE_EFFECT_REVIEW_SEALED_2023",
        "  current_user_request: "+old_protocol["authority"]["current_user_request"]:"  current_user_request: 2026-10-05_explicit_remaining_Step5_request_internal_quadratic_fitting_complete_keep_new_effects_sealed",
        "  current_pre_update_snapshot: docs/v2/v6_2/archive/before_canopy_support_step5_20261004":"  current_pre_update_snapshot: docs/v2/v6_2/archive/before_quadratic_step5_20261005",
        "  Step5_predictor_audit_executed: true":"  Step5_predictor_audit_executed: true\n  Step5_internal_quadratic_executed: true",
        "- audit_predictor_support_before_proposed_quadratic_sensitivity":"- review_completed_quadratic_sensitivity_after_authorized_effect_release",
    }
    for a,b in changes.items():
        if text.count(a) != 1: raise ValueError("Protocol amendment anchor changed")
        text = text.replace(a,b)
    text += "\n"+yaml.safe_dump({TAG:section}, sort_keys=False, allow_unicode=True)
    p.write_text(text)
    current = yaml.load(text, Loader=UniqueLoader)
    normalized = copy.deepcopy(current); normalized.pop(TAG)
    for key in ("updated_on", "status", "next_actions_not_executed"): normalized[key] = old_protocol[key]
    for key in ("current_user_request", "current_pre_update_snapshot"): normalized["authority"][key] = old_protocol["authority"][key]
    normalized["control_boundary"].pop("Step5_internal_quadratic_executed")
    if normalized != old_protocol: raise ValueError("Unplanned protocol change")
    decision = dict(status=completion["status"], fitting_scope_question="RESOLVED_BY_EXPLICIT_USER_CONTINUATION",
                    fitting_hold_superseded=True, authorized_computation_complete=True, full_effect_review_complete=False,
                    effects="SEALED_USER_REQUEST", scientific_curvature_conclusion=None, model_replacement=False,
                    scale_ruling=None, new_time_inference=False, expansion=False, completion=completion)
    write(EXEC/"decision_record.json", decision)
    write(EXEC/"documentation_verification.json", dict(status="PASS", unique_yaml_keys=True,
        unrelated_protocol_fields_unchanged=True, source_archives_verified=True, active_document_count=6,
        prior_decisions_preserved=True, fitting_hold_resolved=True, effect_release_not_authorized=True,
        public_precision_figure_visually_checked=True, synthetic_template_visually_checked=True,
        empirical_effect_figures_visually_checked=False,
        documented_manifest_script_sha256=sha(Path(__file__))))


if __name__ == "__main__": main()

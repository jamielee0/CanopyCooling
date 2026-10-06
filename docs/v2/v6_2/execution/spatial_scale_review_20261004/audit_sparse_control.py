"""Outcome-blind explanation of reported joint draw rank failures; no refits."""
import json
import hashlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[5]
sys.path.insert(0,str(ROOT/"src"))
from v6_2_advance.run_spatial_review import Reader
from v6_2_advance.spatial_review import common_ids, identity_hash, physical_groups, digest
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path

EXEC=Path(__file__).resolve().parent
PUB=ROOT/"outputs/v6_2/scientific/spatial_scale_review_20261004"


def run():
    freeze=json.loads((EXEC/"execution_freeze.json").read_text())
    audit_freeze=EXEC/"sparse_control_audit_freeze.json"
    spec=dict(trigger="48 reported non-estimable joint draws; very sparse nonthermal bare-cover distribution",
        method="identify common blocks with max(bare)>min(bare); reconstruct original frozen multinomial multiplicities and test exact absence of those block/group contributions",
        note="zero is mathematical absence/constant control, not an inclusion cutoff; no new fit, draw replacement or rule change",
        code_sha256=digest(Path(__file__)), source_freeze_sha256=digest(EXEC/"execution_freeze.json"),
        empirical_effect_arrays_read=False, private_members_read=["valid"], outcome_columns_read=False)
    if audit_freeze.exists():assert json.loads(audit_freeze.read_text())==spec
    else:audit_freeze.write_text(json.dumps(spec,indent=2)+"\n")
    reader=Reader(freeze)
    passes=sorted([r for r in freeze["passes"] if r["city"]=="phoenix"],key=lambda r:r["date"])
    frame_path=lambda r:f"outputs/v6_2/sealed_coefficients/{r['run_id']}/{r['orbit']}_paired_native_cells_SEALED.parquet"
    ids=common_ids([reader.frame(frame_path(r),["cell_id"]) for r in passes])
    assert len(ids)==196090
    base=reader.frame(frame_path(passes[0]),["cell_id","block","bare_fraction"])
    common=base[base.cell_id.isin(ids)]
    b=common.groupby("block").bare_fraction.agg(["min","max"])
    informative=b.index[b["max"]>b["min"]].to_numpy(str)
    checks=[]
    for r in passes:
        labels=np.unique(reader.frame(frame_path(r),["block"]).block.astype(str))
        union=np.union1d(labels,b.index.to_numpy(str))
        for size in (1,8):
            groups=np.unique(physical_groups(union,size))
            information_groups=np.unique(physical_groups(informative,size))
            index=np.searchsorted(groups,information_groups)
            assert np.array_equal(groups[index],information_groups)
            rng=np.random.default_rng(20261004+int(r["orbit"]))
            missing=[]
            for _ in range(1000):
                counts=rng.multinomial(len(groups),np.full(len(groups),1/len(groups)))
                missing.append(counts[index].sum()==0)
            path=guarded_output_path(ROOT,"sealed",f"spatial_scale_review_20261004/{r['orbit']}_joint_original_common_{size}km_SEALED.npz")
            with np.load(path,allow_pickle=False) as z:valid=z["valid"]
            assert valid.shape==(1000,) and valid.dtype==bool
            missing=np.asarray(missing,bool)
            checks.append(dict(orbit=str(r["orbit"]),date=r["date"],group_km=size,
                bare_informative_common_blocks=len(informative),bare_informative_groups=len(information_groups),
                draws_without_common_bare_information=int(missing.sum()),reported_joint_nonestimable_draws=int((~valid).sum()),
                mismatch_count=int(np.count_nonzero(missing!=(~valid))),private_validity_file_sha256=digest(path)))
    result=dict(status="OUTCOME_BLIND_RANK_AUDIT_COMPLETE",common_cells=len(common),common_identity_sha256=identity_hash(ids),
        common_cells_with_positive_bare_fraction=int((common.bare_fraction>0).sum()),
        common_blocks_with_within_block_bare_variation=len(informative),
        information_groups_8km=len(np.unique(physical_groups(informative,8))),checks=checks,
        reported_joint_nonestimable_draws=sum(r["reported_joint_nonestimable_draws"] for r in checks),
        draws_without_common_bare_information=sum(r["draws_without_common_bare_information"] for r in checks),
        all_failures_exactly_match_absence_of_common_bare_variation=all(r["mismatch_count"]==0 for r in checks),
        new_fits=0,new_draws_replaced=0,coefficient_or_effect_values_read=False,outcome_columns_read=False,
        source_predictor_accesses=reader.access,
        interpretation="A retained confounder can be unidentified in a spatial resample; record non-estimability rather than dropping it after seeing the draw. This is not an effect-size or stability verdict.")
    (PUB/"sparse_control_rank_audit.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("status","common_cells_with_positive_bare_fraction","common_blocks_with_within_block_bare_variation","information_groups_8km","reported_joint_nonestimable_draws","draws_without_common_bare_information","all_failures_exactly_match_absence_of_common_bare_variation")},indent=2))


if __name__=="__main__":run()

"""Prediction intervals and a verifiable commit gate for advisor Step 3."""
import hashlib
from pathlib import Path
import subprocess
import numpy as np
import pandas as pd
from .advisor_step2_models import fit_pass_model

ORBITS={6281,6510,33496,33623,40111,40192,40376}


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def predictions(training,targets):
    if len(training)!=11 or set(training.city)!={'phoenix'} or set(training.population)!={'original'}:
        raise ValueError('Use the eleven original-population Phoenix training passes')
    if set(targets.orbit)!=ORBITS or len(targets)!=7:
        raise ValueError('Wrong held-out identities')
    if not np.isfinite(targets[['shortwave_W_m2','after_noon']]).all().all():
        raise ValueError('Missing prediction inputs')
    if not targets.after_noon.eq((targets.apparent_solar_hour>12).astype(int)).all():
        raise ValueError('After-noon convention changed')
    model=fit_pass_model(training,'shortwave_W_m2')
    frame=model.get_prediction(targets).summary_frame(alpha=.05)
    result=targets.reset_index(drop=True).copy()
    for col in frame:result[col]=frame[col].to_numpy()
    for arm in [0,1]:
        lo,hi=training.loc[training.after_noon==arm,'shortwave_W_m2'].agg(['min','max'])
        idx=result.after_noon==arm
        result.loc[idx,'outside_training_arm_shortwave_range']=~result.loc[idx,'shortwave_W_m2'].between(lo,hi)
    return model,result


def verify_committed_bundle(repo,commit,files,root):
    """Require all frozen files to match both local bytes and a real Git commit."""
    def git(*args):
        return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True).stdout
    if not files or not commit:raise ValueError('Prediction commit is missing')
    try:
        actual=git('rev-parse','--verify',commit+'^{commit}').decode().strip()
        if actual!=commit:raise ValueError('Full prediction commit SHA required')
        git('merge-base','--is-ancestor',commit,'HEAD')
        for name,sha in files.items():
            if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Invalid committed path')
            if digest(Path(root)/name)!=sha:raise ValueError('Local prediction bytes changed')
            if hashlib.sha256(git('show',f'{commit}:{name}')).hexdigest()!=sha:
                raise ValueError('Committed prediction bytes differ')
    except subprocess.CalledProcessError as error:
        raise ValueError('Prediction commit could not be verified') from error
    return True


def temperature_estimate(path):
    """Read only model-name metadata and coefficient/draw arrays, never native cells."""
    with np.load(path,allow_pickle=False) as z:
        names=z['predictor_names'].astype(str).tolist();outcomes=z['outcome_names'].astype(str).tolist()
        if names.count('canopy_fraction')!=1 or outcomes.count('LST_K')!=1:
            raise ValueError('Unexpected archived model schema')
        i,j=names.index('canopy_fraction'),outcomes.index('LST_K')
        coefficient=float(z['coefficients'][i,j])
        draws=-.1*z['bootstrap_coefficients'][:,i,j]
    if not np.isfinite(coefficient) or not np.isfinite(draws).all():
        raise ValueError('Archived failed/nonfinite draws need clarification; do not replace')
    return {'cooling':-.1*coefficient,'q025':float(np.quantile(draws,.025)),
            'q975':float(np.quantile(draws,.975)),'SE':float(np.std(draws,ddof=1)),'draws':len(draws)}


def coverage(observed,mean,low,high):
    a=np.asarray([observed,mean,low,high],float)
    if not np.isfinite(a).all() or not low<=mean<=high:raise ValueError('Invalid prediction comparison')
    return {'observed_minus_predicted':float(observed-mean),'inside_prediction_interval':bool(low<=observed<=high)}

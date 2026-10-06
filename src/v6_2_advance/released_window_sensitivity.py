"""Post-disclosure joint uncertainty on existing footprint/model sensitivities."""
import numpy as np
from .spatial_review import block_stats


def reference_quadratic_stats(frame,f0,f1,context):
    """Algebraic reparameterization, not a changed quadratic mean model.

    g(f)=f²-(f0+f1)f has identical values at f0 and f1, so the first
    coefficient times (f1-f0) is the complete finite contrast. Raw f² is
    formed before block centering and every original control is retained.
    """
    if not np.isclose(f1-f0,.1,atol=1e-12,rtol=0):raise ValueError('Expected frozen10pp endpoints')
    d=frame.copy();f=d.canopy_fraction.to_numpy(float)
    d['quadratic_reference_basis']=f*f-(f0+f1)*f
    return block_stats(d,['canopy_fraction','quadratic_reference_basis',*context])

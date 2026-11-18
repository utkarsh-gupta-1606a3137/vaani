"""Vaani public API; importing this package never loads a speech model."""
__version__ = "0.1.0"
from .types import SynthesisRequest, SynthesisResult, VaaniError

def synthesize(request, *, root=None, progress=None):
    from .api import synthesize as implementation
    return implementation(request, root=root, progress=progress)

"""Generic runner engine for ``profiles/*.yaml`` backend profiles.

See ``docs/profile-spec.md`` at the repository root for the specification
this package implements: :mod:`.profile` (the profile YAML shape),
:mod:`.manifest` (the manifest JSON shape + context resolution),
:mod:`.template` (``${token}`` substitution into graphs), :mod:`.selector`
(variant selection), :mod:`.cost` (dry-run time estimates), :mod:`.client`
(a minimal ComfyUI HTTP client), :mod:`.runner` (dry-run + real
orchestration), and :mod:`.report` (the delivery report shape).
"""

from __future__ import annotations

from .client import ComfyUIClient, ComfyUIClientLike, ComfyUIError, ServerNotReadyError
from .cost import CostError, CostEstimate, JobCost, estimate
from .manifest import Manifest, ManifestError, ManifestJob, load_manifest, resolve_context
from .profile import (
    Constraints,
    CostModel,
    OutputSpec,
    Profile,
    ProfileError,
    Resolution,
    SelectorRule,
    ServerSpec,
    Variant,
    VariantSelector,
    load_profile,
)
from .report import DeliveryReport, JobReport, resolve_output_file
from .runner import ConstraintIssue, DryRunReport, JobTimeoutError, dry_run, run
from .selector import SelectorError, select_variant
from .template import TemplateError, build_graph, render_template_string

__all__ = [
    "ComfyUIClient",
    "ComfyUIClientLike",
    "ComfyUIError",
    "ConstraintIssue",
    "Constraints",
    "CostEstimate",
    "CostError",
    "CostModel",
    "DeliveryReport",
    "DryRunReport",
    "JobCost",
    "JobReport",
    "JobTimeoutError",
    "Manifest",
    "ManifestError",
    "ManifestJob",
    "OutputSpec",
    "Profile",
    "ProfileError",
    "Resolution",
    "SelectorError",
    "SelectorRule",
    "ServerNotReadyError",
    "ServerSpec",
    "TemplateError",
    "Variant",
    "VariantSelector",
    "build_graph",
    "dry_run",
    "estimate",
    "load_manifest",
    "load_profile",
    "render_template_string",
    "resolve_context",
    "resolve_output_file",
    "run",
    "select_variant",
]

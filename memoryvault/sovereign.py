"""Sovereign editions (year-2) — data residency & regulatory profiles.

One config switch pins an org to a jurisdiction: where data may live, which
compliance regime applies, and residency enforcement. This is how you ship
EU-only, India-DPDP, and government editions from one codebase.

    MV_SOVEREIGN=eu | india | us | gov
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class SovereignProfile:
    name: str
    allowed_regions: tuple
    regime: str
    residency_required: bool
    notes: str


PROFILES = {
    "us": SovereignProfile(
        "United States", ("us-east-1", "us-west-2"), "SOC2/CCPA",
        False, "Default commercial edition."),
    "eu": SovereignProfile(
        "European Union", ("eu-west-1", "eu-central-1"), "GDPR/EU-AI-Act/Data-Act",
        True, "Data must remain in EU regions; SCCs for any transfer."),
    "india": SovereignProfile(
        "India", ("ap-south-1", "ap-south-2"), "DPDP-Act-2023",
        True, "DPDP data-localization; sovereign-AI mission eligible."),
    "gov": SovereignProfile(
        "Government", ("us-gov-west-1",), "FedRAMP-aligned",
        True, "Air-gapped/GovCloud; no cross-border, no federation."),
}


def active_profile() -> SovereignProfile:
    return PROFILES.get(os.environ.get("MV_SOVEREIGN", "us").lower(),
                        PROFILES["us"])


def region_allowed(region: str) -> bool:
    p = active_profile()
    return (not p.residency_required) or region in p.allowed_regions


def federation_allowed() -> bool:
    """Government/air-gapped editions may not join the shared network."""
    return active_profile().name != "Government"


def status() -> dict:
    p = active_profile()
    return {"edition": p.name, "regime": p.regime,
            "allowed_regions": list(p.allowed_regions),
            "residency_required": p.residency_required,
            "federation_allowed": federation_allowed(), "notes": p.notes}

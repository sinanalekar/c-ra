"""Apple target universe + coverage engine (master prompt
sections 15-18, 27). Every target is searchable, filterable,
assignable, hypothesis-generatable, experiment-generatable, and
coverage-tracked on ACTUAL recorded experiments - never fabricated
numbers."""
from __future__ import annotations

CATEGORIES = {
    "AUTHENTICATION": ["Activation Lock", "Face ID",
                       "Lock Screen", "Touch ID"],
    "KERNEL": ["Graphics - AMD", "Graphics - NVIDIA",
               "Graphics - Intel", "Kexts",
               "Operating System Mitigations", "XNU"],
    "SAFARI": ["JavaScriptCore", "Safari", "WebKit"],
    "SERVICES": ["Apple Pay", "FaceTime", "Find My", "Home/"
                 "HomeKit", "iCloud", "iMessage",
                 "Private Cloud Compute"],
    "SYSTEM": ["CarPlay", "FileVault", "Gatekeeper",
               "Screen Time", "Siri"],
    "USERLAND": ["Daemons and Frameworks",
                 "Parsing - Audio", "Parsing - Video",
                 "Parsing - Images", "Parsing - Text",
                 "Sandbox", "TCC"],
    "WIRELESS TECHNOLOGIES": ["AirDrop", "Baseband",
                               "Bluetooth",
                               "Location Services", "Wi-Fi"],
    "APPLE APPS": ["Final Cut Pro", "GarageBand", "Mail",
                   "Podcasts", "Shortcuts",
                   "Swift Playgrounds", "iMovie", "iTunes",
                   "iWork", "Other Apps"],
    "OTHER": ["3rd-party Apps", "Compromised Certificate",
              "Cryptography", "Law Enforcement", "Malware",
              "Notarization", "Open Source", "Phishing",
              "Privacy", "Security", "Not Listed"],
}

APPLE_SERVICE_CLASSES = (
    "Authentication Bypass", "Improper Access Control", "IDOR",
    "MFA Bypass", "Weak Session Management", "Blind XSS",
    "DOM XSS", "Reflected XSS", "Stored XSS",
    "Apple Confidential Data", "PII/PHI/PCI",
    "Server Environment", "Weak/Exposed Credential",
    "Cache Poisoning", "Clickjacking",
    "Content Spoofing/Input Validation", "CSRF", "CORS", "DoS",
    "Domain/Subdomain Takeover", "Email/SMTP Misconfiguration",
    "EOL/Outdated Library", "Insecure Deserialization",
    "Open/Improper/Host-Header Redirect", "Path Traversal",
    "Private Cloud Compute", "Proxy Misconfiguration", "RCE",
    "RFI/LFI", "Request Smuggling/Response Splitting", "SQLi",
    "SSRF", "SSTI", "TLS Certificate/Crypto/Protocol "
    "Misconfiguration", "XXE", "Feedback", "Not Listed",
)

ENGINE_FIT = {
    "AUTHENTICATION": ("seek", "cider"),
    "KERNEL": ("hydra", "frontier"),
    "SAFARI": ("cider", "frontier"),
    "SERVICES": ("seek", "cider"),
    "SYSTEM": ("hydra", "cider"),
    "USERLAND": ("cider", "hydra"),
    "WIRELESS TECHNOLOGIES": ("seek", "cider"),
    "APPLE APPS": ("seek",),
    "OTHER": ("seek", "frontier"),
}


def _tid(category: str, subcategory: str) -> str:
    slug = subcategory.lower().replace(" ", "-") \
        .replace("/", "-").replace(".", "")
    cslug = category.lower().split()[0]
    return f"T-{cslug}-{slug}"


class TargetRecord(dict):
    """The target data model (section 18)."""

    @classmethod
    def make(cls, parent_category, subcategory):
        rec = cls(
            target_id=_tid(parent_category, subcategory),
            parent_category=parent_category,
            category=subcategory,
            subcategory="",
            product=subcategory,
            platform="apple",
            component="",
            attack_surface="",
            vulnerability_classes=[],
            versions="",
            build_range="",
            authorization_requirement="authorized research only",
            required_capabilities=["experimental_execution"],
            applicable_engines=list(
                ENGINE_FIT.get(parent_category, ("cider",))),
            available_artifacts=[],
            experiment_templates=[],
            known_controls=[],
            negative_controls=[],
            coverage_state="untested",
            evidence_state="none",
            last_researched=None,
            next_research_action="map attack surface",
        )
        return rec


class TargetUniverse:
    """The searchable, coverage-tracked target universe. Coverage
    is computed from recorded experiments only."""

    def __init__(self):
        self.targets: dict[str, TargetRecord] = {}
        for cat, subs in CATEGORIES.items():
            for sub in subs:
                rec = TargetRecord.make(cat, sub)
                self.targets[rec["target_id"]] = rec

    def search(self, query: str = "",
               category: str | None = None) -> list:
        q = query.lower()
        out = []
        for t in self.targets.values():
            if category and t["parent_category"] != category:
                continue
            if q and q not in t["target_id"].lower() and \
                    q not in t["product"].lower():
                continue
            out.append(dict(t))
        return out

    def get(self, target_id: str) -> TargetRecord | None:
        return self.targets.get(target_id)

    def record_experiment(self, target_id: str,
                          experiment) -> dict:
        """Update coverage from an ACTUAL recorded experiment."""
        t = self.targets.get(target_id)
        if t is None:
            return {"error": "unknown target"}
        t["last_researched"] = experiment.get("ts")
        t["coverage_state"] = "single-experiment"
        if experiment.get("has_negative_control"):
            t["negative_controls"].append(
                experiment.get("experiment_id"))
            t["coverage_state"] = "controlled"
        if experiment.get("reproduced"):
            t["coverage_state"] = "reproduced"
        if experiment.get("evidence"):
            t["evidence_state"] = "recorded"
        return {"target_id": target_id,
                "coverage_state": t["coverage_state"]}

    def coverage_report(self) -> dict:
        by_state: dict[str, int] = {}
        for t in self.targets.values():
            by_state[t["coverage_state"]] = \
                by_state.get(t["coverage_state"], 0) + 1
        untested = [t["target_id"] for t in
                    self.targets.values()
                    if t["coverage_state"] == "untested"]
        return {
            "total_targets": len(self.targets),
            "by_coverage_state": by_state,
            "untested_count": len(untested),
            "untested_sample": untested[:20],
            "note": "computed from recorded experiments only",
        }

    def for_target(self, target_id: str) -> dict:
        """Section 19: the automatic experiment-generation
        questions, answered structurally per target."""
        t = self.targets.get(target_id)
        if t is None:
            return {"error": "unknown target"}
        return {
            "target": t["target_id"],
            "attack_surface": t["attack_surface"] or
                              "unmapped - first action: map it",
            "trust_boundary": "per-category default "
                              "(see methodology)",
            "applicable_engines": t["applicable_engines"],
            "experiment_templates":
                t["experiment_templates"] or
                ["differential testing",
                 "invariant testing",
                 "negative-control testing"],
            "required_capabilities":
                t["required_capabilities"],
            "research_gaps": (
                ["attack surface unmapped"]
                if not t["attack_surface"] else []) +
                (["no negative controls recorded"]
                 if not t["negative_controls"] else []) +
                (["not reproduced"]
                 if t["coverage_state"] != "reproduced" else []),
        }

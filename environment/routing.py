"""Deeper engine routing (master prompt sections 15, 19, 20).

For each target the router answers the twelve experiment-design
questions structurally, determines applicable engines and
experiment templates, ranks candidate experiments by impact /
tractability / novelty / uncertainty / evidence value / cost /
authorization burden / safety risk, and produces the minimal
design. It never runs identical experiments against every
target: templates are chosen by attack surface and vulnerability
class."""
from __future__ import annotations

from .targets import ENGINE_FIT

# experiment templates per engine (section 20)
TEMPLATES = {
    "cider": {
        "fuzzing": ("event-feedback fuzzing on a parser/state "
                    "machine target", 0.7, 0.9),
        "invariant_testing": ("invariant monitors over flawed "
                              "vs repaired controls", 0.8, 0.9),
        "grammar_testing": ("induced-grammar mutation testing",
                            0.6, 0.8),
        "state_machine_testing": ("auth/session state "
                                  "transitions", 0.8, 0.85),
    },
    "veritas": {
        "dialectic_battery": ("falsification battery on the "
                              "claim", 0.7, 0.95),
        "causal_testing": ("causal/counterfactual state "
                           "experiments", 0.75, 0.85),
    },
    "hydra": {
        "pattern_scan": ("pattern scan of the kernelcache "
                         "(STATIC_CANDIDATE)", 0.5, 0.9),
        "cross_version_diff": ("cross-version differential of "
                               "build pairs", 0.7, 0.7),
        "static_triage": ("structural triage of candidate "
                          "families", 0.6, 0.8),
    },
    "seek": {
        "http_differential": ("authorized HTTP differential "
                              "testing", 0.7, 0.6),
        "auth_boundary_testing": ("authentication-boundary "
                                  "probes in scope", 0.8, 0.5),
        "parser_behavior": ("parser behavior comparison", 0.6,
                            0.6),
    },
    "frontier": {
        "method_benchmark": ("discover or benchmark a method "
                             "when existing ones are "
                             "insufficient", 0.6, 0.6),
        "ood_transfer_study": ("OOD robustness of a discovered "
                               "detector", 0.5, 0.7),
    },
}

CAPABILITY_COST = {
    "experimental_execution": 0.1,
    "firmware_tooling": 0.4,
    "network": 0.6,
    "device_access": 0.8,
    "packet_capture": 0.7,
}

VULN_CLASS_TEMPLATES = {
    "auth_boundary": ("cider", "state_machine_testing"),
    "session_management": ("cider", "state_machine_testing"),
    "memory_safety": ("hydra", "pattern_scan"),
    "kernel_surface": ("hydra", "cross_version_diff"),
    "parsing": ("cider", "fuzzing"),
    "web_endpoint": ("seek", "http_differential"),
    "protocol": ("seek", "parser_behavior"),
    "method_gap": ("frontier", "method_benchmark"),
}


def design_questions(target: dict) -> dict:
    """The twelve questions of section 19, answered structurally
    from the target record."""
    has_artifacts = bool(target.get("available_artifacts"))
    return {
        "1_attack_surface": target.get("attack_surface") or
                            "unmapped (first action: map it)",
        "2_trust_boundary": _trust_boundary(target),
        "3_security_property": _security_property(target),
        "4_state_transitions":
            "session/auth-state model applies"
            if "auth" in target["target_id"].lower() or \
            target["parent_category"] in
            ("AUTHENTICATION", "SERVICES")
            else "target-specific",
        "5_boundary_crossing_inputs":
            "parser inputs, requests, pairing traffic"
            if has_artifacts else "protocol/requests (no "
                                   "artifact staged)",
        "6_parser_protocol":
            _parser_protocol(target),
        "7_authorization_checks":
            "session, token, entitlement checks apply"
            if target["parent_category"] in
            ("AUTHENTICATION", "SYSTEM", "USERLAND", "SERVICES")
            else "target-specific",
        "8_expected_mitigations":
            "PAC/CSL guards (kernel), sandbox/TCC (userland), "
            "CORS/CSRF stack (web)",
        "9_differential_versions":
            "version watcher available via HYDRA",
        "10_negative_controls":
            "repaired control variants (cider), benign twins "
            "(veritas worlds), clean components (hydra)",
        "11_falsifying_experiments":
            "the coordinator's negative-control + reproduction "
            "gates",
        "12_sufficient_evidence":
            "SUPPORTED requires evidence objects + passing "
            "negative controls + independent reproduction",
    }


def _trust_boundary(t: dict) -> str:
    cat = t["parent_category"]
    return {
        "KERNEL": "user-kernel boundary (syscalls, IPC)",
        "SAFARI": "web-content boundary (parser, JIT)",
        "USERLAND": "sandbox/TCC entitlement boundary",
        "WIRELESS TECHNOLOGIES":
            "device-adjacent protocol trust boundary",
        "AUTHENTICATION": "authenticator boundary "
                          "(state, token, biometric gating)",
        "SERVICES": "client-service trust boundary",
    }.get(cat, "component boundary")


def _security_property(t: dict) -> str:
    cat = t["parent_category"]
    if cat == "KERNEL":
        return "memory safety + privilege separation"
    if cat in ("SAFARI",):
        return "memory safety + origin isolation"
    if cat in ("USERLAND", "SYSTEM"):
        return "authorization integrity (entitlements, TCC)"
    if cat == "AUTHENTICATION":
        return "authentication state integrity"
    if cat == "SERVICES":
        return "authorization + session integrity"
    return "authorization integrity"


def _parser_protocol(t: dict) -> str:
    cat = t["parent_category"]
    if cat == "KERNEL":
        return "Mach-O/fileset, syscall argument parsers"
    if cat == "SAFARI":
        return "HTML/JS/WASM parsers"
    if cat in ("USERLAND", "APPLE APPS"):
        return "media/document parsers"
    if cat == "WIRELESS TECHNOLOGIES":
        return "pairing/discovery protocols"
    return "HTTP/JSON protocol surfaces"


def rank_experiments(target: dict) -> list:
    """Rank candidate experiments. Score balances impact,
    tractability, novelty, evidence value against cost,
    authorization burden, and safety risk (section 19)."""
    engines = target.get("applicable_engines") or \
        list(ENGINE_FIT.get(target["parent_category"],
                            ("cider",)))
    out = []
    for engine in engines:
        for kind, (desc, impact, tract) in \
                TEMPLATES[engine].items():
            auth = CAPABILITY_COST.get(
                "network" if engine == "seek" else
                "firmware_tooling" if engine == "hydra" else
                "experimental_execution", 0.1)
            cost = 0.2 if engine in ("cider", "veritas") \
                else 0.4
            novelty = 0.5
            evidence_value = (impact + tract) / 2
            score = (impact + tract + novelty +
                     evidence_value) / 4 - \
                (cost + auth) / 2
            out.append({
                "engine": engine, "template": kind,
                "description": desc,
                "impact": impact, "tractability": tract,
                "novelty": novelty,
                "evidence_value": evidence_value,
                "cost": cost, "authorization_burden": auth,
                "safety_risk": "low"
                if engine != "seek" else "medium",
                "score": round(score, 3),
            })
    out.sort(key=lambda x: -x["score"])
    return out


def route(target: dict, vulnerability_class: str = "") -> dict:
    """The deep routing decision for a target: the ranked
    experiment list plus a vulnerability-class-specific primary
    template, the required capabilities, and the controls to
    stage. The design questions ride along."""
    ranked = rank_experiments(target)
    primary = None
    key = None
    for k, (engine, template) in \
            VULN_CLASS_TEMPLATES.items():
        if k in vulnerability_class.lower() or \
                k in target["target_id"].lower():
            key = k
            primary = {"engine": engine,
                       "template": template}
            break
    chosen = primary or {
        "engine": ranked[0]["engine"] if ranked
        else "cider",
        "template": ranked[0]["template"] if ranked
        else "invariant_testing"}
    caps = {"cider": ["experimental_execution"],
            "veritas": ["experimental_execution"],
            "hydra": ["firmware_tooling",
                      "experimental_execution"],
            "seek": ["network", "experimental_execution"],
            "frontier": ["experimental_execution"],
            }.get(chosen["engine"], [])
    return {
        "target_id": target["target_id"],
        "vulnerability_class": vulnerability_class or
                               "generic",
        "chosen": chosen,
        "matched_class": key,
        "ranked_experiments": ranked[:5],
        "required_capabilities": caps,
        "controls_to_stage":
            "repaired control / benign twins / clean component",
        "design_questions": design_questions(target),
    }

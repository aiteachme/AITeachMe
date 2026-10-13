"""Exact-service Kubernetes metadata probe. No exec, logs or Secret access.

Pass the existing sanitized kubectl(namespace, *args) helper. This module never
calls Kubernetes on import and intentionally has no command-line entrypoint.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import re

NAMESPACE = "ns-icbq3ltw"
SERVICE = "test-db-postgresql"
SAFE_REASONS = {
    "OOMKilled", "Error", "Completed", "ContainerCannotRun", "StartError",
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "ContainerCreating",
    "PodInitializing", "CreateContainerConfigError", "CreateContainerError",
    "RunContainerError", "DeadlineExceeded", "Evicted",
}
SAFE_PHASES = {"Pending", "Running", "Succeeded", "Failed", "Unknown"}


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", value):
        raise ValueError("Invalid resource identity")
    return value


def _uid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,128}", value):
        raise ValueError("Missing resource UID")
    return value


def _number(value, maximum=1_000_000_000):
    return value if type(value) is int and 0 <= value <= maximum else None


def _quantity(value, *, cpu=False):
    """Normalize K8s quantities to numeric millicores/bytes without echoing input."""
    if type(value) not in {str, int, float}:
        return None
    match = re.fullmatch(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))([eE][+-]?\d+|[numkKMGTPE]|[KMGTPE]i)?", str(value))
    if not match:
        return None
    suffix = match[2] or ""
    decimal_scales = {"": 1, "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"),
                      "k": 10**3, "K": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15, "E": 10**18}
    try:
        if suffix.endswith("i"):
            scale = Decimal(1024) ** ("KMGTPE".index(suffix[0]) + 1)
        elif suffix.startswith(("e", "E")) and len(suffix) > 1:
            exponent = int(suffix[1:])
            if not -30 <= exponent <= 30:
                return None
            scale = Decimal(10) ** exponent
        else:
            scale = Decimal(decimal_scales[suffix])
        quantity = Decimal(match[1]) * scale * (1000 if cpu else 1)
        if not quantity.is_finite() or not 0 <= quantity <= 2**63 - 1:
            return None
        return int(quantity.to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, KeyError, ValueError):
        return None


def _state(value):
    result = {}
    if not isinstance(value, dict):
        return result
    for kind in ("running", "waiting", "terminated"):
        item = value.get(kind)
        if not isinstance(item, dict):
            continue
        state = {"reason": item.get("reason") if item.get("reason") in SAFE_REASONS else "unknown"}
        if type(item.get("exitCode")) is int and -255 <= item["exitCode"] <= 255:
            state["exit_code"] = item["exitCode"]
        if _number(item.get("signal"), 64) is not None:
            state["signal"] = item["signal"]
        result[kind] = state
    return result


def _resource_numbers(resources):
    result = {}
    for scope in ("requests", "limits"):
        configured = resources.get(scope, {})
        result[scope] = {
            "cpu_millicores": _quantity(configured.get("cpu"), cpu=True),
            "memory_bytes": _quantity(configured.get("memory")),
            "ephemeral_storage_bytes": _quantity(configured.get("ephemeral-storage")),
        }
    return result


def diagnose_database_pods(kubectl, namespace=NAMESPACE, service=SERVICE):
    """Fail closed unless exact endpoint Pod UID and controller UID both match."""
    if namespace != NAMESPACE or service != SERVICE:
        return {"database_pod_diagnostics": "rejected_scope"}

    def get(kind, name):
        data = json.loads(kubectl(namespace, "get", f"{kind}/{_name(name)}", "-o", "json"))
        meta = data.get("metadata", {})
        if meta.get("name") != name or meta.get("namespace") != namespace:
            raise ValueError("Resource scope mismatch")
        _uid(meta.get("uid"))
        return data

    stage = "service"
    controller_kind = "unknown"
    try:
        svc = get("service", service)
        stage = "service_selector"
        selectors = svc.get("spec", {}).get("selector", {})
        if not isinstance(selectors, dict) or not selectors:
            raise ValueError("Service must select database pods")
        stage = "endpoints"
        endpoints = get("endpoints", service)
        stage = "endpoint_targets"
        targets = {}
        for subset in endpoints.get("subsets", []):
            for address in subset.get("addresses", []) + subset.get("notReadyAddresses", []):
                target = address.get("targetRef", {})
                if target.get("kind") != "Pod" or target.get("namespace", namespace) != namespace:
                    raise ValueError("Endpoint must refer to a Pod in this namespace")
                name, uid = _name(target.get("name")), _uid(target.get("uid"))
                if name in targets and targets[name] != uid:
                    raise ValueError("Conflicting endpoint UID")
                targets[name] = uid
        if not targets:
            raise ValueError("No exact database endpoint Pod")

        records, controllers = [], {}
        for name, endpoint_uid in sorted(targets.items()):
            stage = "pod"
            pod = get("pod", name)
            stage = "pod_identity"
            meta = pod["metadata"]
            if meta["uid"] != endpoint_uid:
                raise ValueError("Endpoint target Pod UID changed")
            if any(meta.get("labels", {}).get(key) != value for key, value in selectors.items()):
                raise ValueError("Endpoint Pod does not match the service selector")
            stage = "controller_kind"
            owners = [owner for owner in meta.get("ownerReferences", []) if owner.get("controller") is True]
            if len(owners) == 1 and owners[0].get("kind") in {"StatefulSet", "InstanceSet", "ReplicaSet"}:
                controller_kind = owners[0]["kind"]
            resources = {("StatefulSet", "apps/v1"): "statefulset",
                         ("InstanceSet", "workloads.kubeblocks.io/v1alpha1"): "instanceset.workloads.kubeblocks.io",
                         ("InstanceSet", "workloads.kubeblocks.io/v1"): "instanceset.workloads.kubeblocks.io",
                         ("InstanceSet", "apps.kubeblocks.io/v1alpha1"): "instanceset.apps.kubeblocks.io"}
            identity = (owners[0].get("kind"), owners[0].get("apiVersion", "apps/v1")) if len(owners) == 1 else None
            controller_resource = resources.get(identity)
            if not controller_resource:
                raise ValueError("Database Pod needs one recognized controller")
            owner_name, owner_uid = _name(owners[0].get("name")), _uid(owners[0].get("uid"))
            stage = "controller_identity"
            if owner_name not in controllers:
                controllers[owner_name] = get(controller_resource, owner_name)
            if controllers[owner_name]["metadata"]["uid"] != owner_uid:
                raise ValueError("StatefulSet controller UID changed")

            status = pod.get("status", {})
            record = {"phase": status.get("phase") if status.get("phase") in SAFE_PHASES else "Unknown",
                      "terminating": bool(meta.get("deletionTimestamp")),
                      "ready": any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions", [])),
                      "containers": []}
            for spec_key, status_key, kind in (("containers", "containerStatuses", "regular"),
                                               ("initContainers", "initContainerStatuses", "init")):
                statuses = {c.get("name"): c for c in status.get(status_key, [])}
                for index, container in enumerate(pod.get("spec", {}).get(spec_key, [])):
                    state = statuses.get(container.get("name"), {})
                    record["containers"].append({"kind": kind, "index": index,
                                                 "ready": state.get("ready") is True,
                                                 "restarts": _number(state.get("restartCount")),
                                                 "state": _state(state.get("state")),
                                                 "last_state": _state(state.get("lastState")),
                                                 "resources": _resource_numbers(container.get("resources", {}))})
            records.append(record)
        return {"database_pod_diagnostics": "verified", "pod_count": len(records), "pods": records}
    except Exception:
        # No exception strings, resource JSON, selectors, IPs or environment data.
        return {"database_pod_diagnostics": "unavailable", "stage":stage, "controller_kind":controller_kind}

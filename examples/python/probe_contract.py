"""Minimum checks shared by the example and live discovery probes."""

import json
import re
import sys

CALCULATOR = "urn:sbrm:calculator:fbt:car-operating-cost"
PERIOD = "urn:sbrm:period:fbt:fy2026"
TOOL = "fbt-car-operating-cost"


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("Non-standard JSON numeric constant")


def decode_json(raw: str | bytes) -> object:
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)


def validate_discovery(value: object) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Discovery must be an array of calculator objects")
    for item in value:
        if item.get("calc_uri") == CALCULATOR:
            periods = item.get("supported_periods")
            if (isinstance(periods, list) and all(isinstance(p, str) for p in periods)
                    and PERIOD in periods):
                return
    raise ValueError("Discovery does not advertise the example calculator and period")


def validate_calculation(value: object) -> None:
    if not isinstance(value, dict) or "error" in value:
        raise ValueError("Calculation must be a result object")
    amount = value.get("taxable_value")
    if not isinstance(amount, str) or re.fullmatch(r"-?[0-9]+\.[0-9]{2}", amount) is None:
        raise ValueError("Calculation must contain a taxable_value string with two decimal places")
    advisory = value.get("advisory")
    disclaimer = advisory.get("disclaimer") if isinstance(advisory, dict) else None
    if not isinstance(disclaimer, str) or not disclaimer.strip():
        raise ValueError("Calculation must contain an advisory disclaimer")


def validate_tools(value: object) -> None:
    if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0"
            or type(value.get("id")) is not int or value["id"] != 1 or "error" in value):
        raise ValueError("MCP tools/list must return a successful JSON-RPC 2.0 response for id 1")
    result = value.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if (not isinstance(tools, list) or not all(isinstance(item, dict) for item in tools)
            or not any(item.get("name") == TOOL for item in tools)):
        raise ValueError("MCP tools/list does not advertise the example tool")


if __name__ == "__main__":
    checks = {"discovery": validate_discovery, "mcp": validate_tools}
    if len(sys.argv) != 2 or sys.argv[1] not in checks:
        sys.exit("Usage: probe_contract.py discovery|mcp < response.json")
    try:
        checks[sys.argv[1]](decode_json(sys.stdin.read()))
    except ValueError as error:
        sys.exit(f"Probe failed: {error}")
    print("Required capability is available")

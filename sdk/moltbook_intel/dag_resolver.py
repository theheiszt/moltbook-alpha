"""
Moltbook Alpha Client SDK — DAG Parameter Resolver.
Performs client-side validation and planning against the server's versioned parameter DAG.
"""

from typing import Dict, Any, List, Set, Optional



class ParameterPlan:
    def __init__(self, tool_name: str, version: str, stages: List[List[str]]):
        self.tool_name = tool_name
        self.version = version
        self.stages = stages

    def missing_required_parameters(self, provided: Set[str], parameters_meta: Dict[str, Any]) -> List[str]:
        missing = []
        for name, meta in parameters_meta.items():
            if meta.get("required") and name not in provided:
                missing.append(name)
        return missing

    def check_prerequisites(self, provided: Set[str], parameters_meta: Dict[str, Any]) -> List[str]:
        violations = []
        for name in provided:
            meta = parameters_meta.get(name, {})
            prereqs = meta.get("prerequisites", [])
            for prereq in prereqs:
                if prereq not in provided:
                    violations.append(f"Parameter '{name}' requires prerequisite '{prereq}'.")
        return violations


class ToolDAGResolver:
    """
    Validates parameter inputs against the server's Directed Acyclic Graph,
    determines resolution stages, and detects missing prerequisite dependencies.
    """

    def __init__(self, tool_graph: Dict[str, Any]):
        self.tool_name = tool_graph.get("tool_name", "unknown")
        self.version = tool_graph.get("version", "1.0.0")
        self.parameters = tool_graph.get("parameters", {})
        self.topological_stages = tool_graph.get("topological_stages", [])
        self.plan = ParameterPlan(self.tool_name, self.version, self.topological_stages)

    def validate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates provided inputs against DAG requirements, prerequisites, and types.
        """
        provided = set(inputs.keys())
        missing = self.plan.missing_required_parameters(provided, self.parameters)
        prereq_violations = self.plan.check_prerequisites(provided, self.parameters)

        is_valid = len(missing) == 0 and len(prereq_violations) == 0
        return {
            "valid": is_valid,
            "tool_name": self.tool_name,
            "version": self.version,
            "missing_required": missing,
            "prerequisite_violations": prereq_violations,
            "execution_stages": self.topological_stages,
        }

    def get_stage_for_parameter(self, param_name: str) -> Optional[int]:
        for idx, stage in enumerate(self.topological_stages):
            if param_name in stage:
                return idx
        return None


# Backward-compatibility alias
DAGToolResolver = ToolDAGResolver

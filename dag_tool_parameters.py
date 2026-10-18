"""
DAG-Based Tool Parameters Engine for Autonomous Agent Orchestration.
Provides deterministic parameter graph construction, cycle detection via DFS/Kahn,
topological staged execution planning, and structured dependency errors.
"""

from typing import Dict, Any, List, Optional, Callable
from pydantic import BaseModel, Field


class ParameterDependencyCycleError(Exception):
    def __init__(self, cycle_path: List[str]):
        self.cycle_path = cycle_path
        path_str = " -> ".join(cycle_path)
        super().__init__(f"Cycle detected in parameter dependencies: {path_str}")


class ParameterUnsatisfiedDependencyError(Exception):
    def __init__(self, parameter: str, missing_prerequisites: List[str], condition: Optional[str] = None):
        self.parameter = parameter
        self.missing_prerequisites = missing_prerequisites
        self.condition = condition
        msg = f"Parameter '{parameter}' is missing prerequisite(s): {', '.join(missing_prerequisites)}"
        if condition:
            msg += f" (Condition: {condition})"
        super().__init__(msg)


class ParameterNode(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    default: Optional[Any] = None
    optional: bool = False
    enum: Optional[List[Any]] = None
    depends_on: List[str] = Field(default_factory=list)
    condition: Optional[str] = None
    resolver: Optional[str] = None


class ToolParameterDAG:
    """
    Directed Acyclic Graph representing tool parameter prerequisites,
    staged validation order, and dynamic resolvers.
    """

    def __init__(
        self,
        tool_name: str,
        version: str = "1.0.0",
        description: str = "",
        parameters: Optional[Dict[str, ParameterNode]] = None,
        resolvers: Optional[Dict[str, Callable[..., Any]]] = None,
    ):
        self.tool_name = tool_name
        self.version = version
        self.description = description
        self.parameters: Dict[str, ParameterNode] = parameters or {}
        self.resolvers: Dict[str, Callable[..., Any]] = resolvers or {}

        # Validate graph topology immediately on initialization
        self.validate_graph()

    def add_parameter(self, node: ParameterNode) -> "ToolParameterDAG":
        self.parameters[node.name] = node
        self.validate_graph()
        return self

    def register_resolver(self, name: str, fn: Callable[..., Any]) -> "ToolParameterDAG":
        self.resolvers[name] = fn
        return self

    def validate_graph(self) -> None:
        """
        Validates graph integrity:
        1. Checks that all prerequisite dependencies exist in parameter dictionary.
        2. Detects directed cycles using DFS 3-color vertex marking.
        """
        for name, node in self.parameters.items():
            for dep in node.depends_on:
                if dep not in self.parameters:
                    raise ValueError(f"Parameter '{name}' depends on non-existent parameter '{dep}'.")

        # Cycle detection via DFS with recursion stack tracking
        # Colors: 0 = unvisited (white), 1 = visiting / active in path (gray), 2 = visited (black)
        state: Dict[str, int] = {k: 0 for k in self.parameters}
        path: List[str] = []

        def dfs(u: str) -> None:
            state[u] = 1
            path.append(u)
            for v in self.parameters[u].depends_on:
                if state[v] == 1:
                    # v is already in current recursion stack -> cycle detected
                    cycle_start = path.index(v)
                    cycle_nodes = path[cycle_start:] + [v]
                    raise ParameterDependencyCycleError(cycle_nodes)
                elif state[v] == 0:
                    dfs(v)
            path.pop()
            state[u] = 2

        for k in self.parameters:
            if state[k] == 0:
                dfs(k)

    def get_topological_stages(self) -> List[List[str]]:
        """
        Groups parameters into parallel execution stages using Kahn's algorithm.
        Stage 0 contains parameters with in-degree 0 (no prerequisites).
        Stage N contains parameters whose prerequisites are satisfied by Stages 0 .. N-1.
        """
        self.validate_graph()

        in_degree: Dict[str, int] = {k: 0 for k in self.parameters}
        adj: Dict[str, List[str]] = {k: [] for k in self.parameters}

        for name, node in self.parameters.items():
            in_degree[name] = len(node.depends_on)
            for dep in node.depends_on:
                adj[dep].append(name)

        stages: List[List[str]] = []
        current_stage = [k for k, deg in in_degree.items() if deg == 0]

        while current_stage:
            current_stage.sort()  # Deterministic tie-breaking
            stages.append(current_stage)
            next_stage: List[str] = []
            for u in current_stage:
                for v in adj[u]:
                    in_degree[v] -= 1
                    if in_degree[v] == 0:
                        next_stage.append(v)
            current_stage = next_stage

        return stages

    def resolve_and_validate(
        self,
        inputs: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes staged parameter evaluation, validating inputs and resolving dynamic fields.
        """
        resolved: Dict[str, Any] = dict(inputs)
        ctx = context or {}
        stages = self.get_topological_stages()

        for stage in stages:
            for param_name in stage:
                node = self.parameters[param_name]

                # Check condition predicate if present
                if node.condition:
                    # Simple evaluation against resolved inputs
                    should_evaluate = self._eval_condition(node.condition, resolved)
                    if not should_evaluate:
                        continue

                # Verify all explicit prerequisites are already resolved
                missing = [dep for dep in node.depends_on if dep not in resolved]
                if missing:
                    raise ParameterUnsatisfiedDependencyError(
                        parameter=param_name,
                        missing_prerequisites=missing,
                        condition=node.condition,
                    )

                # If parameter not provided by user, try default or dynamic resolver
                if param_name not in resolved or resolved[param_name] is None:
                    if node.resolver and node.resolver in self.resolvers:
                        fn = self.resolvers[node.resolver]
                        resolved[param_name] = fn(resolved, ctx)
                    elif node.default is not None:
                        resolved[param_name] = node.default
                    elif not node.optional:
                        raise ParameterUnsatisfiedDependencyError(
                            parameter=param_name,
                            missing_prerequisites=[f"required parameter '{param_name}' missing"],
                        )

                # Type / Enum checks
                val = resolved.get(param_name)
                if val is not None and node.enum is not None:
                    if val not in node.enum:
                        raise ValueError(f"Parameter '{param_name}' must be one of: {node.enum}")

        return resolved

    def _eval_condition(self, condition: str, values: Dict[str, Any]) -> bool:
        """Safely evaluates equality conditions like 'asset == USDC'."""
        if "==" in condition:
            parts = [p.strip().strip("'\"") for p in condition.split("==")]
            if len(parts) == 2:
                k, target = parts[0], parts[1]
                return str(values.get(k, "")) == target
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Exports inspectable JSON metadata for client and agent discovery."""
        stages = self.get_topological_stages()
        return {
            "tool_name": self.tool_name,
            "version": self.version,
            "description": self.description,
            "topological_stages": stages,
            "parameter_count": len(self.parameters),
            "parameters": {
                name: {
                    "name": node.name,
                    "type": node.type,
                    "description": node.description,
                    "default": node.default,
                    "optional": node.optional,
                    "enum": node.enum,
                    "depends_on": node.depends_on,
                    "condition": node.condition,
                    "has_resolver": bool(node.resolver),
                }
                for name, node in self.parameters.items()
            },
        }


# ==============================================================================
# Built-in Standard Tool DAGs for Moltbook Alpha API
# ==============================================================================

def _resolve_amount_raw(params: Dict[str, Any], ctx: Dict[str, Any]) -> int:
    tier = params.get("target_tier", "tier_starter")
    asset = params.get("asset", "USDC")
    rates = {
        "tier_starter": {"USDC": 1_000_000, "SOL": 5_000_000},
        "tier_pro": {"USDC": 5_000_000, "SOL": 25_000_000},
        "tier_unlimited": {"USDC": 20_000_000, "SOL": 100_000_000},
        "tier_premium": {"USDC": 20_000_000, "SOL": 100_000_000},
    }
    return rates.get(tier, {}).get(asset, 1_000_000)


def create_invoice_dag() -> ToolParameterDAG:
    dag = ToolParameterDAG(
        tool_name="create_payment_invoice",
        version="1.0.0",
        description="Generates a Solana Pay payment invoice with zero-knowledge claim credentials.",
    )
    dag.add_parameter(ParameterNode(
        name="target_tier",
        type="string",
        enum=["tier_starter", "tier_pro", "tier_unlimited", "tier_premium"],
        default="tier_starter",
        description="Target subscription tier to purchase.",
    ))
    dag.add_parameter(ParameterNode(
        name="asset",
        type="string",
        enum=["USDC", "SOL"],
        default="USDC",
        description="Settlement asset.",
    ))
    dag.add_parameter(ParameterNode(
        name="cluster",
        type="string",
        enum=["mainnet-beta", "devnet"],
        default="mainnet-beta",
        description="Target Solana network cluster.",
    ))
    dag.add_parameter(ParameterNode(
        name="amount_raw",
        type="integer",
        depends_on=["target_tier", "asset"],
        resolver="calc_amount_raw",
        description="Raw token units or lamports computed from tier and asset.",
    ))
    dag.add_parameter(ParameterNode(
        name="expected_payer",
        type="string",
        optional=True,
        description="Optional Base58 payer public key.",
    ))
    dag.register_resolver("calc_amount_raw", _resolve_amount_raw)
    return dag


def verify_payment_dag() -> ToolParameterDAG:
    dag = ToolParameterDAG(
        tool_name="verify_solana_payment",
        version="1.0.0",
        description="Server-authoritative on-chain settlement verification.",
    )
    dag.add_parameter(ParameterNode(
        name="transaction_signature",
        type="string",
        description="Base58 transaction signature (88 chars).",
    ))
    dag.add_parameter(ParameterNode(
        name="invoice_id",
        type="string",
        optional=True,
        description="Target invoice identifier.",
    ))
    dag.add_parameter(ParameterNode(
        name="claim_secret",
        type="string",
        optional=True,
        description="Recovery secret starting with sec_.",
    ))
    return dag


TOOL_DAG_REGISTRY: Dict[str, ToolParameterDAG] = {
    "create_payment_invoice": create_invoice_dag(),
    "verify_solana_payment": verify_payment_dag(),
}

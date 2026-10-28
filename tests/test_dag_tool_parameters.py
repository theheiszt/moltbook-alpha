"""
Automated Tests for DAG-Based Tool Parameters Engine.
Tests parameter graph construction, cycle detection, Kahn topological sorting,
dynamic resolver execution, and FastAPI discovery endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from api_server import app
from dag_tool_parameters import (
    ToolParameterDAG,
    ParameterNode,
    ParameterDependencyCycleError,
    ParameterUnsatisfiedDependencyError,
    TOOL_DAG_REGISTRY,
)
from errors import ErrorCode


def test_dag_construction_and_topological_stages():
    dag = ToolParameterDAG(tool_name="test_tool")
    dag.add_parameter(ParameterNode(name="p_root1", type="string"))
    dag.add_parameter(ParameterNode(name="p_root2", type="integer"))
    dag.add_parameter(ParameterNode(name="p_child", type="string", depends_on=["p_root1", "p_root2"]))
    dag.add_parameter(ParameterNode(name="p_grandchild", type="string", depends_on=["p_child"]))

    stages = dag.get_topological_stages()
    assert len(stages) == 3
    # Stage 0: Roots
    assert set(stages[0]) == {"p_root1", "p_root2"}
    # Stage 1: Child
    assert stages[1] == ["p_child"]
    # Stage 2: Grandchild
    assert stages[2] == ["p_grandchild"]


def test_cycle_detection_three_nodes():
    dag = ToolParameterDAG(tool_name="cycle_tool")
    dag.add_parameter(ParameterNode(name="node_a", type="string"))
    dag.add_parameter(ParameterNode(name="node_b", type="string", depends_on=["node_a"]))

    # Now create cycle: node_a depends on node_c, node_c depends on node_b
    dag.add_parameter(ParameterNode(name="node_c", type="string", depends_on=["node_b"]))

    with pytest.raises(ParameterDependencyCycleError) as exc_info:
        dag.add_parameter(ParameterNode(name="node_a", type="string", depends_on=["node_c"]))

    err = exc_info.value
    assert "node_a" in err.cycle_path
    assert "node_b" in err.cycle_path
    assert "node_c" in err.cycle_path


def test_non_existent_dependency_fails_validation():
    dag = ToolParameterDAG(tool_name="missing_dep_tool")
    with pytest.raises(ValueError) as exc:
        dag.add_parameter(ParameterNode(name="child", type="string", depends_on=["non_existent_parent"]))
    assert "depends on non-existent parameter" in str(exc.value)


def test_dynamic_resolver_execution():
    dag = ToolParameterDAG(tool_name="resolver_tool")
    dag.add_parameter(ParameterNode(name="tier", type="string", enum=["starter", "pro"], default="starter"))
    dag.add_parameter(ParameterNode(
        name="computed_credits",
        type="integer",
        depends_on=["tier"],
        resolver="resolve_credits",
    ))
    dag.register_resolver("resolve_credits", lambda p, ctx: 300 if p.get("tier") == "pro" else 50)

    # 1. Resolve with default tier (starter)
    res_starter = dag.resolve_and_validate({})
    assert res_starter["tier"] == "starter"
    assert res_starter["computed_credits"] == 50

    # 2. Resolve with pro tier
    res_pro = dag.resolve_and_validate({"tier": "pro"})
    assert res_pro["tier"] == "pro"
    assert res_pro["computed_credits"] == 300


def test_unsatisfied_dependency_error():
    dag = ToolParameterDAG(tool_name="unsatisfied_tool")
    dag.add_parameter(ParameterNode(name="parent", type="string"))
    dag.add_parameter(ParameterNode(name="child", type="string", depends_on=["parent"]))

    # Omit parent when child requires it
    with pytest.raises(ParameterUnsatisfiedDependencyError) as exc:
        dag.resolve_and_validate({}, context={})
    assert "parent" in str(exc.value)


def test_built_in_invoice_dag_resolution():
    invoice_dag = TOOL_DAG_REGISTRY["create_payment_invoice"]
    stages = invoice_dag.get_topological_stages()
    assert len(stages) >= 2

    # Roots in stage 0
    assert "target_tier" in stages[0]
    assert "asset" in stages[0]
    assert "cluster" in stages[0]

    # Dependent amount_raw in stage 1
    assert "amount_raw" in stages[1]

    # Test dynamic calculation of amount_raw for Pro tier in USDC
    resolved = invoice_dag.resolve_and_validate({"target_tier": "tier_pro", "asset": "USDC"})
    assert resolved["target_tier"] == "tier_pro"
    assert resolved["asset"] == "USDC"
    assert resolved["amount_raw"] == 5_000_000  # $5.00 USDC


def test_api_tool_catalog_and_graph_endpoints():
    client = TestClient(app)

    # 1. GET /v1/tools
    resp_tools = client.get("/v1/tools")
    assert resp_tools.status_code == 200
    tools_data = resp_tools.json()
    assert "tools" in tools_data
    tool_names = [t["tool_name"] for t in tools_data["tools"]]
    assert "create_payment_invoice" in tool_names
    assert "verify_solana_payment" in tool_names

    # 2. GET /v1/tools/create_payment_invoice/parameter-graph
    resp_graph = client.get("/v1/tools/create_payment_invoice/parameter-graph")
    assert resp_graph.status_code == 200
    graph_data = resp_graph.json()
    assert graph_data["tool_name"] == "create_payment_invoice"
    assert "topological_stages" in graph_data
    assert len(graph_data["topological_stages"]) >= 2
    assert "parameters" in graph_data
    assert "amount_raw" in graph_data["parameters"]
    assert graph_data["parameters"]["amount_raw"]["depends_on"] == ["target_tier", "asset"]

    # 3. GET non-existent tool graph -> 404 with RESOURCE_NOT_FOUND
    resp_404 = client.get("/v1/tools/non_existent_tool_xyz/parameter-graph")
    assert resp_404.status_code == 404
    err_data = resp_404.json()
    assert err_data["code"] == ErrorCode.RESOURCE_NOT_FOUND.value

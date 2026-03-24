from __future__ import annotations

from typing import TypedDict, Optional, Any, Literal


IntentType = Literal["analyze", "trend", "anomaly", "list", "unknown"]

AnalysisHint = Literal[
    "profile", "sensitivity", "worst_case", "tradeoff",
    "correlation", "interpolation", None
]


class ParsedIntent(TypedDict):
    """intent_parser 출력"""
    intent: IntentType
    entities: dict[str, Any]
    missing_params: list[str]
    raw_question: str


class ResolvedPDK(TypedDict):
    """단일 PDK 해석 결과"""
    pdk_id: int
    process: str
    project: str
    project_name: str
    mask: str
    dk_gds: str
    is_golden: int
    hspice: str
    lvs: str
    pex: str
    vdd_nominal: float


class PDKResolution(TypedDict):
    """pdk_resolver 출력"""
    target_pdks: list[ResolvedPDK]
    comparison_mode: Literal["single", "pair", "multi"]
    resolved_params: dict[str, Any]
    applied_defaults: dict[str, str]


class QueryPlan(TypedDict):
    """query_builder 출력"""
    queries: list[dict[str, Any]]
    is_bulk: bool


class QueryResult(TypedDict):
    """data_executor 출력"""
    datasets: list[dict[str, Any]]
    total_rows: int
    warnings: list[str]


class AnalysisResult(TypedDict):
    """analyzer 출력"""
    mode: str
    summary_table: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    chart_data: dict[str, Any]
    raw_for_avg: Optional[dict[str, Any]]


class Interpretation(TypedDict):
    """interpreter 출력"""
    narrative: str
    key_insights: list[str]
    recommendations: list[str]
    suggested_charts: list[dict[str, Any]]
    additional_analysis: list[str]


class ChartSpec(TypedDict):
    """visualizer 출력"""
    chart_type: str
    title: str
    plotly_spec: dict


class FinalResponse(TypedDict):
    """response_formatter 출력 (API 응답)"""
    text: str
    data_tables: list[dict[str, Any]]
    charts: list[ChartSpec]
    applied_defaults: dict[str, str]
    metadata: dict[str, Any]


class PaveAgentState(TypedDict):
    """LangGraph 전체 상태"""

    # 입력
    user_question: str
    conversation_id: str
    conversation_history: list[dict[str, Any]]
    screen_context: Optional[dict[str, Any]]

    # 노드 출력
    parsed_intent: Optional[ParsedIntent]
    pdk_resolution: Optional[PDKResolution]
    query_plan: Optional[QueryPlan]
    query_result: Optional[QueryResult]
    analysis_result: Optional[AnalysisResult]
    interpretation: Optional[Interpretation]
    chart_specs: Optional[list[ChartSpec]]
    final_response: Optional[FinalResponse]

    # 앱 기동 시 로드된 PDK 카탈로그 (list → response_formatter 직접 참조)
    available_pdks: Optional[list[dict[str, Any]]]

    # fallback
    fallback_result: Optional[dict[str, Any]]

    # 공통
    route: Literal["distributed", "fallback", "list"]
    error: Optional[str]

    # anomaly SSE 진행상황
    anomaly_progress: Optional[dict[str, Any]]

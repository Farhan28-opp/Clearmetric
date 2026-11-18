"""The structured analysis plan: the only contract between language understanding and computation.

Natural-language interpreters (local or Claude) and the visual query builder all produce this object.
It is validated server-side before anything executes."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.analytics.filters import Filter

Intent = Literal["aggregate", "rank", "breakdown", "contribution", "trend", "compare_periods", "compare_segments",
                 "decompose_change", "distribution", "outliers", "describe_dataset"]
Aggregation = Literal["sum", "avg", "min", "max", "count", "count_distinct", "median"]
Grain = Literal["day", "week", "month", "quarter", "year"]
Viz = Literal["auto", "bar", "hbar", "line", "area", "stacked_bar", "donut", "histogram", "scatter", "heatmap",
              "kpi", "table", "waterfall"]

INTENT_LABELS = {
    "aggregate": "Total / summary value", "rank": "Ranking", "breakdown": "Breakdown by dimension",
    "contribution": "Contribution to total", "trend": "Trend over time", "compare_periods": "Period comparison",
    "compare_segments": "Segment comparison", "decompose_change": "Change decomposition",
    "distribution": "Distribution", "outliers": "Outlier detection", "describe_dataset": "Dataset description",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeasureRef(Strict):
    kind: Literal["metric", "column", "count_rows"]
    metric_id: str | None = Field(default=None, max_length=32)
    column: str | None = Field(default=None, max_length=64)
    aggregation: Aggregation | None = None


class TimeSpec(Strict):
    column: str = Field(max_length=64)
    grain: Grain | None = None
    start: date | None = None
    end: date | None = None  # inclusive


class Period(Strict):
    start: date
    end: date  # inclusive


class ComparisonSpec(Strict):
    mode: Literal["previous_period", "previous_year", "custom"] = "previous_period"
    grain: Grain = "month"
    current: Period | None = None
    baseline: Period | None = None


class Focus(Strict):
    column: str = Field(max_length=64)
    values: list[str] = Field(min_length=1, max_length=50)


class Sort(Strict):
    by: Literal["value", "dimension", "period"] = "value"
    direction: Literal["asc", "desc"] = "desc"


class Options(Strict):
    bins: int = Field(default=20, ge=3, le=60)
    outlier_method: Literal["iqr", "zscore"] = "iqr"
    outlier_threshold: float = Field(default=1.5, gt=0, le=10)
    expected_direction: Literal["decrease", "increase", "any"] = "any"
    max_series: int = Field(default=8, ge=1, le=12)


class AnalysisPlan(Strict):
    version: Literal[1] = 1
    intent: Intent
    dataset_id: str = Field(max_length=32)
    measures: list[MeasureRef] = Field(default_factory=list, max_length=4)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    time: TimeSpec | None = None
    comparison: ComparisonSpec | None = None
    focus: Focus | None = None
    sort: Sort = Field(default_factory=Sort)
    limit: int = Field(default=50, ge=1, le=500)
    visualization: Viz = "auto"
    options: Options = Field(default_factory=Options)

"""Validate consumer configuration without disclosing its contents in errors."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from spwf.state import State


class ConfigError(ValueError):
    """A safe-to-log configuration error."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Lists(_StrictModel):
    doing: str = Field(min_length=1)
    blocked: str = Field(min_length=1)
    review: str = Field(min_length=1)
    done_prefix: str = Field(min_length=1)
    reference: str = "📌 Program & Gates"

    @field_validator("doing", "blocked", "review", "done_prefix", "reference")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("list names must not be blank")
        return value

    @model_validator(mode="after")
    def distinct_stages(self):
        names = [self.doing, self.blocked, self.review, self.reference]
        if len(set(names)) != len(names):
            raise ValueError("workflow stages must use distinct lists")
        return self


class WorkflowConfig(_StrictModel):
    board: str = Field(pattern=r"^(?:[A-Za-z0-9]{8}|[a-f0-9]{24})$")
    prefix: Literal["ws", "ig", "ec", "got", "ag", "te", "pg", "si", "web", "prg"]
    lists: Lists
    experiment_label: str = Field(default="T: Experiment", min_length=1)
    allow_done_from_push: bool = True
    timezone: str = "America/Vancouver"
    done_month_format: Literal["%Y-%m", "%B", "%B %Y"] | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid timezone") from None
        return value

    def current_month(self, now: datetime | None = None) -> str:
        if self.done_month_format is None:
            raise ConfigError("Configure done_month_format after verifying the board's Done list")
        current = now or datetime.now(ZoneInfo(self.timezone))
        if current.tzinfo is None:
            raise ConfigError("Current time must include a timezone")
        current = current.astimezone(ZoneInfo(self.timezone))
        # English names independent of the worker's locale.
        month = ("January February March April May June July August September October November December".split())[current.month - 1]
        return {"%Y-%m": f"{current.year:04d}-{current.month:02d}",
                "%B": month, "%B %Y": f"{month} {current.year}"}[self.done_month_format]


    @field_validator("experiment_label")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value

    def target_list(self, state: State, *, month_label: str | None = None) -> str:
        """Resolve a logical state to a configured name.

        The caller supplies the board's exact current-month suffix for Done.
        Its format is intentionally not guessed before board validation.
        """
        if state == State.DONE:
            if not month_label or not month_label.strip():
                raise ConfigError("Done requires the board's current-month label")
            return self.lists.done_prefix + month_label
        return getattr(self.lists, state.value)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently changing a consumer's policy."""


def _mapping(loader, node):
    pairs = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        try:
            if key in pairs:
                raise ConfigError("workflow.yaml contains duplicate keys")
            pairs[key] = loader.construct_object(value_node)
        except TypeError:
            raise ConfigError("workflow.yaml keys must be scalar values") from None
    return pairs


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_config(path: str | Path) -> WorkflowConfig:
    try:
        content = Path(path).read_text(encoding="utf-8")
        data = yaml.load(content, Loader=_UniqueKeyLoader)
        return WorkflowConfig.model_validate(data)
    except ConfigError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, RecursionError):
        # Parser/model exceptions may embed secret-looking values or whole lines.
        raise ConfigError("Cannot load workflow.yaml: check its path, syntax and schema") from None

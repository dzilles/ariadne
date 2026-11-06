from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import StrEnum

from ariadne._util import JsonModel


class Component(StrEnum):
    ORCHESTRATOR = "orchestrator"
    AGENT = "agent"
    CONTEXT_SERVICE = "context_service"
    RUNTIME = "runtime"
    GIT_TRACKER = "git_tracker"
    WORKFLOW_ENGINE = "workflow_engine"
    TOOL = "tool"


@dataclass
class Provider(JsonModel):
    id: str
    adapter: str
    base_url: str
    credential_ref: str

    def validate(self):
        from .validation import validate_provider
        validate_provider(self)


@dataclass
class Prompt(JsonModel):
    id: str
    text: str
    variables: list[str] = field(default_factory=list)


@dataclass
class Profile(JsonModel):
    id: str
    component: str
    description: str = ""
    prompt_ids: list[str] = field(default_factory=list)
    model: str | None = None
    provider_id: str | None = None
    credential_ref: str | None = None  # Legacy manifests remain readable.
    tools: list[str] = field(default_factory=list)
    settings: dict = field(default_factory=dict)


@dataclass
class Step(JsonModel):
    agent_profile: str
    transitions: dict[str, dict]
    inputs: list[str] = field(default_factory=list)


@dataclass
class Workflow(JsonModel):
    id: str
    start: str
    steps: dict[str, Step]
    max_step_executions: int = 12

    def __post_init__(self):
        if isinstance(self.steps, dict):
            self.steps = {k: Step.from_dict(v) if isinstance(v, dict) else v for k, v in self.steps.items()}


@dataclass
class Configuration(JsonModel):
    prompts: dict[str, Prompt] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)
    workflows: dict[str, Workflow] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)

    def __post_init__(self):
        from ariadne.errors import Error
        for name, cls in [("prompts", Prompt), ("profiles", Profile), ("workflows", Workflow), ("providers", Provider)]:
            values = getattr(self, name)
            if not isinstance(values, dict):
                raise Error.invalid(f"{name} must be an object")
            setattr(self, name, {k: cls.from_dict(v) if isinstance(v, dict) else v for k, v in values.items()})

    def validate(self):
        from .validation import validate
        validate(self)

    def validate_tools(self, available):
        from ariadne.errors import Error
        for profile in self.profiles.values():
            for tool in profile.tools:
                if tool not in available:
                    raise Error.invalid(f"Profile {profile.id} references unavailable tool {tool}")

    def render_profile(self, profile_id, values):
        from ariadne.errors import Error
        from .validation import render
        self.validate()
        if profile_id not in self.profiles:
            raise Error("NOT_FOUND", f"Profile {profile_id} does not exist")
        profile = self.profiles[profile_id]
        required = {var for name in profile.prompt_ids for var in self.prompts[name].variables}
        if not isinstance(values, dict) or set(values) != required or any(not isinstance(v, str) for v in values.values()):
            raise Error.invalid(f"Expected prompt inputs {sorted(required)}")
        return ResolvedProfile(copy.deepcopy(profile), [RenderedPrompt(name, render(self.prompts[name], values)) for name in profile.prompt_ids])


@dataclass
class Snapshot(JsonModel):
    id: str
    revision: int
    configuration: Configuration

    def __post_init__(self):
        if isinstance(self.configuration, dict):
            self.configuration = Configuration.from_dict(self.configuration)

    def render_profile(self, profile_id, values):
        return self.configuration.render_profile(profile_id, values)


@dataclass
class RenderedPrompt(JsonModel):
    id: str
    text: str


@dataclass
class ResolvedProfile(JsonModel):
    profile: Profile
    prompts: list[RenderedPrompt]


@dataclass
class ConfigurationStatus(JsonModel):
    revision: int
    providers: int
    profiles: int
    prompts: int
    workflows: int

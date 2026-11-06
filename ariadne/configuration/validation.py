import math
import re
from urllib.parse import urlsplit
import ipaddress

from ariadne._util import identifier, text, strings, integer, enum_value, object_fields, dumps
from ariadne.errors import Error
from .model import Component, Provider, Prompt, Profile, Workflow, Step


def variable(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is not None


def placeholders(prompt):
    text(prompt.text, "prompt text")
    matches, offset = [], 0
    while (start := prompt.text.find("{{", offset)) >= 0:
        end = prompt.text.find("}}", start + 2)
        if end < 0:
            raise Error.invalid("Unclosed prompt placeholder; use {{variable}}")
        name = prompt.text[start + 2:end].strip()
        if not variable(name):
            raise Error.invalid("Invalid prompt placeholder")
        matches.append((start, end + 2, name))
        offset = end + 2
    return matches


def render(prompt, values):
    pieces, offset = [], 0
    for start, end, name in placeholders(prompt):
        if name not in values or not isinstance(values[name], str):
            raise Error.invalid(f"Missing prompt input {name}")
        pieces.extend((prompt.text[offset:start], values[name]))
        offset = end
    return "".join(pieces) + prompt.text[offset:]


def validate_provider(provider):
    identifier(provider.id)
    identifier(provider.adapter)
    url = text(provider.base_url, "API base URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise Error.invalid("Invalid API base URL") from exc
    if not host or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
        raise Error.invalid("API URL needs a host and must not contain credentials, query, or fragment")
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host.lower() == "localhost"
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise Error.invalid("HTTPS required; HTTP allowed only on loopback")
    if port is not None:
        integer(port, "port", 1, 65535)
    if not isinstance(provider.credential_ref, str) or not provider.credential_ref.startswith("env:") or not variable(provider.credential_ref[4:]):
        raise Error.invalid("Credentials must reference env:NAME")


def validate(config):
    for name, cls in [("providers", Provider), ("prompts", Prompt), ("profiles", Profile), ("workflows", Workflow)]:
        for key, record in getattr(config, name).items():
            identifier(key)
            if not isinstance(record, cls) or record.id != key:
                raise Error.invalid(f"{name} map keys must match record IDs and types")
    for provider in config.providers.values():
        validate_provider(provider)
    for prompt in config.prompts.values():
        strings(prompt.variables, "prompt variables", unique=True)
        if not all(variable(v) for v in prompt.variables) or set(prompt.variables) != {p[2] for p in placeholders(prompt)}:
            raise Error.invalid(f"Prompt {prompt.id} variables must match its placeholders")
    for profile in config.profiles.values():
        enum_value(profile.component, Component, "component")
        text(profile.description, "description", empty=True)
        strings(profile.prompt_ids, "prompt references", unique=True)
        strings(profile.tools, "tool references", unique=True)
        if any(name not in config.prompts for name in profile.prompt_ids):
            raise Error.invalid(f"Profile {profile.id} references a missing prompt")
        if profile.component in ("agent", "orchestrator") and (not profile.prompt_ids or profile.model is None):
            raise Error.invalid("LLM profiles require a model and prompts")
        for key in ("model", "provider_id", "credential_ref"):
            if getattr(profile, key) is not None:
                text(getattr(profile, key), key)
        if profile.provider_id is not None:
            if profile.provider_id not in config.providers or profile.model is None or profile.credential_ref is not None:
                raise Error.invalid("Connected profiles need an existing provider and model; put credentials on the provider")
        if not isinstance(profile.settings, dict):
            raise Error.invalid("Profile settings must be an object")
        for key, value in profile.settings.items():
            text(key, "setting name")
            if key in ("token_budget", "context_budget_tokens", "max_tool_calls", "timeout_ms", "max_search_results", "max_step_executions", "max_output_tokens"):
                integer(value, key, 1)
            if key in ("checkpoint_after_tools", "exclude_ignored") and type(value) is not bool:
                raise Error.invalid(f"{key} must be boolean")
            if key in ("temperature", "top_p") and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= (2 if key == "temperature" else 1)):
                raise Error.invalid(f"Invalid {key}")
    for workflow in config.workflows.values():
        validate_workflow(workflow, config)
    try:
        dumps(config)
    except (TypeError, ValueError) as exc:
        raise Error.invalid("Configuration settings must contain finite JSON values") from exc


def validate_workflow(workflow, config):
    identifier(workflow.start)
    integer(workflow.max_step_executions, "max_step_executions", 1)
    if not isinstance(workflow.steps, dict) or workflow.start not in workflow.steps:
        raise Error.invalid("Workflow start step is missing")
    reverse, terminal = {}, set()
    for name, step in workflow.steps.items():
        identifier(name)
        if not isinstance(step, Step) or not isinstance(step.agent_profile, str) or step.agent_profile not in config.profiles or config.profiles[step.agent_profile].component != "agent":
            raise Error.invalid("Workflow steps must reference an agent profile")
        strings(step.inputs, "step inputs", unique=True)
        if not all(variable(v) for v in step.inputs):
            raise Error.invalid("Invalid step input name")
        profile = config.profiles[step.agent_profile]
        required = {v for p in profile.prompt_ids for v in config.prompts[p].variables}
        if not required <= set(step.inputs):
            raise Error.invalid("Workflow step does not supply all prompt inputs")
        if not isinstance(step.transitions, dict) or not step.transitions:
            raise Error.invalid("Workflow steps need transitions")
        for outcome, transition in step.transitions.items():
            identifier(outcome)
            object_fields(transition, ["kind"], ["step"])
            enum_value(transition["kind"], ("step", "completed", "blocked", "cancelled", "failed"), "transition")
            if transition["kind"] == "step":
                target = transition.get("step")
                text(target, "transition target")
                if target not in workflow.steps:
                    raise Error.invalid("Workflow transition target is missing")
                reverse.setdefault(target, set()).add(name)
            elif "step" in transition:
                raise Error.invalid("Terminal transitions cannot name a step")
            else:
                terminal.add(name)
    pending = list(terminal)
    while pending:
        for previous in reverse.get(pending.pop(), ()):
            if previous not in terminal:
                terminal.add(previous)
                pending.append(previous)
    reachable, pending = set(), [workflow.start]
    while pending:
        name = pending.pop()
        if name not in reachable:
            reachable.add(name)
            pending.extend(t["step"] for t in workflow.steps[name].transitions.values() if t["kind"] == "step")
    if len(terminal) != len(workflow.steps) or len(reachable) != len(workflow.steps):
        raise Error.invalid("Every workflow step must be reachable and have a path to a terminal outcome")

"""对外保留模型能力入口；配置解析与参数规则由 core.model_settings 实现。"""

from core.config import settings
from core import model_settings as rules
from core.model_settings import ModelSelection


def _config(config):
    source = settings if config is None else config
    return source.snapshot() if hasattr(source, "snapshot") else source


def model_capability(model, config=None):
    return rules.model_capability(model, _config(config))


def model_catalog(config=None):
    return rules.model_catalog(_config(config))


def resolve_selection(model=None, thinking_mode=None, use_reasoning=None, effort=None, config=None):
    return rules.resolve_selection(model, thinking_mode, use_reasoning, effort, _config(config))


def generation_controls(selection, *, config=None, **kwargs):
    return rules.generation_controls(selection, config=_config(config), **kwargs)


def auxiliary_controls(task, temperature, model=None):
    config = _config(None)
    selection = rules.resolve_task_selection(task, config, model=model)
    controls = rules.generation_controls(selection, temperature=temperature, config=config)
    for key in ("top_p", "presence_penalty", "frequency_penalty"):
        controls.pop(key, None)
    return controls


def validate_settings_updates(updates, config=None):
    source = settings if config is None else config
    source.prepare_update(updates)

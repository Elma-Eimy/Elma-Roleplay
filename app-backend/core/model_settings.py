"""声明模型能力，集中适配思考与采样参数；不调用外部模型服务。"""

from dataclasses import dataclass
import copy
import re



def model_capability(model: str, config=None) -> dict:
    model = model.strip()
    configured = next((item for item in config.LLM_MODEL_PROFILES if isinstance(item, dict) and item.get('id') == model), {})
    name = model.lower().split('/')[-1]
    inferred = 'deepseek' if name.startswith('deepseek-') else 'reasoning' if re.match(r'^o[134](?:-|$)', name) else 'compatible'
    adapter = configured.get('adapter', inferred)
    return {
        'id': model, 'label': configured.get('label') or ('DeepSeek Flash' if name.startswith('deepseek-') and 'flash' in name else 'DeepSeek Pro' if name.startswith('deepseek-') and 'pro' in name else model), 'adapter': adapter,
        'thinking': configured.get('thinking') or ('toggle' if adapter == 'deepseek' else 'always' if adapter == 'reasoning' else 'unsupported'),
        'efforts': configured.get('efforts') if configured.get('efforts') is not None else (['low', 'high', 'max'] if adapter == 'deepseek' else ['low', 'medium', 'high'] if adapter == 'reasoning' else []),
    }


def model_catalog(config=None) -> list[dict]:
    models = [config.LLM_DEFAULT_CHAT_MODEL, config.LLM_MEMORY_MODEL, config.LLM_TTS_PREPROCESS_MODEL,
              config.LLM_TRANSLATION_MODEL]
    models.extend(item['id'] for item in config.LLM_MODEL_PROFILES if isinstance(item, dict) and isinstance(item.get('id'), str))
    return [model_capability(model, config) for model in dict.fromkeys(models) if model]


@dataclass(frozen=True)
class ModelSelection:
    model: str
    thinking: bool
    effort: str | None


def resolve_selection(model=None, thinking_mode=None, use_reasoning=None, effort=None, config=None) -> ModelSelection:
    modern = model is not None or thinking_mode is not None
    if modern:
        model = model or config.LLM_DEFAULT_CHAT_MODEL
    elif use_reasoning is not None:
        model = config.CHAT_MODEL_REASONING if use_reasoning else config.CHAT_MODEL_NON_REASONING
    else:
        model = config.LLM_DEFAULT_CHAT_MODEL
    if thinking_mode not in (None, 'inherit', 'enabled', 'disabled'):
        raise ValueError('无效的思考模式。')
    model = model.strip()
    if not model:
        raise ValueError('模型 ID 不能为空。')
    capability = model_capability(model, config)
    explicit = thinking_mode in ('enabled', 'disabled') or (not modern and use_reasoning is not None)
    thinking = thinking_mode == 'enabled' if thinking_mode in ('enabled', 'disabled') else use_reasoning if not modern and use_reasoning is not None else (getattr(config, "LLM_CHAT_THINKING_MODE", "enabled" if getattr(config, "LLM_REASONING_MODE", False) else "disabled") == "enabled")
    if capability['thinking'] == 'always':
        if explicit and not thinking:
            raise ValueError(f'{model} 是固定思考模型，不能关闭思考。')
        thinking = True
    elif capability['thinking'] == 'unsupported':
        if explicit and thinking:
            raise ValueError(f'{model} 未配置思考能力，请在模型设置中选择正确的适配类型。')
        thinking = False
    effort = config.LLM_REASONING_EFFORT if effort in (None, 'inherit') else effort
    if not capability['efforts']:
        effort = None
    if thinking and not effort and capability['adapter'] != 'deepseek' and capability['thinking'] == 'toggle':
        effort = 'high' if 'high' in capability['efforts'] else next(iter(capability['efforts']), None)
    if capability['adapter'] == 'deepseek' and effort not in capability['efforts']:
        effort = {'minimal': 'low', 'medium': 'high', 'xhigh': 'high', 'ultra': 'max'}.get(effort, effort)
    if thinking and effort and effort not in capability['efforts']:
        raise ValueError(f'{model} 不支持思考强度 {effort}，可选：{", ".join(capability["efforts"])}。')
    return ModelSelection(model, bool(thinking), effort if thinking else None)


def generation_controls(selection: ModelSelection, *, temperature=0.7, top_p=1.0,
                        presence_penalty=0.0, frequency_penalty=0.0, repetition_penalty=None,
                        config=None) -> dict:
    capability = model_capability(selection.model, config)
    kwargs = {}
    if not selection.thinking:
        kwargs.update(temperature=temperature, presence_penalty=presence_penalty,
                      frequency_penalty=frequency_penalty)
    if capability['adapter'] == 'compatible' or (capability['adapter'] == 'deepseek' and not selection.thinking):
        kwargs['top_p'] = top_p
    if capability['adapter'] == 'deepseek':
        flash = 'flash' in selection.model.lower()
        if flash:
            kwargs.pop('top_p', None)
            if selection.thinking:
                kwargs['top_p'] = min(1.0, max(0.95, top_p))
        kwargs['extra_body'] = {'thinking': {'type': 'enabled' if selection.thinking else 'disabled'}}
    if not selection.thinking and capability['thinking'] == 'toggle' and capability['adapter'] != 'deepseek':
        kwargs['reasoning_effort'] = 'none'
    if selection.thinking and selection.effort:
        kwargs['reasoning_effort'] = selection.effort
    # 非标准参数仅用于通用兼容端点，不向 DeepSeek/固定推理模型盲传。
    if capability['adapter'] == 'compatible' and repetition_penalty is not None and abs(repetition_penalty - 1.0) > 1e-5:
        kwargs.setdefault('extra_body', {})['repetition_penalty'] = repetition_penalty
    return kwargs


TASK_FIELDS = {
    "memory": ("LLM_MEMORY_MODEL", "LLM_MEMORY_THINKING_MODE", "LLM_MEMORY_REASONING_EFFORT"),
    "tts": ("LLM_TTS_PREPROCESS_MODEL", "LLM_TTS_THINKING_MODE", "LLM_TTS_REASONING_EFFORT"),
    "translation": ("LLM_TRANSLATION_MODEL", "LLM_TRANSLATION_THINKING_MODE", "LLM_TRANSLATION_REASONING_EFFORT"),
}
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}


def resolve_task_selection(task, config, *, model=None):
    model_field, mode_field, effort_field = TASK_FIELDS[task]
    model = model or getattr(config, model_field)
    mode = getattr(config, mode_field)
    if model_capability(model, config)["thinking"] == "always":
        mode = "inherit"
    task_config = copy.copy(config)
    task_config.LLM_REASONING_EFFORT = None
    return resolve_selection(model=model, thinking_mode=mode,
                             effort=getattr(config, effort_field), config=task_config)


def validate_model_settings(config, *, updates=(), legacy_chat=False):
    profiles = config.LLM_MODEL_PROFILES
    if not isinstance(profiles, list) or len(profiles) > 100:
        raise ValueError("model_profiles 必须是最多 100 项的模型配置列表。")
    seen = set()
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) - {"id", "label", "adapter", "thinking", "efforts"}:
            raise ValueError("模型配置字段无效。")
        model = profile.get("id")
        if not isinstance(model, str) or not model.strip() or model != model.strip() or len(model) > 200 or model in seen:
            raise ValueError("模型 ID 必须非空且不能重复。")
        seen.add(model)
        if not isinstance(profile.get("label", ""), str) or len(profile.get("label", "")) > 200:
            raise ValueError("模型显示名称必须是不超过 200 字符的文本。")
        if profile.get("adapter", "compatible") not in ("compatible", "deepseek", "reasoning"):
            raise ValueError("模型适配类型无效。")
        if profile.get("thinking") not in (None, "toggle", "always", "unsupported"):
            raise ValueError("模型思考能力无效。")
        efforts = profile.get("efforts")
        if efforts is not None and (not isinstance(efforts, list) or any(not isinstance(e, str) or e not in EFFORTS for e in efforts)
                                    or len(set(efforts)) != len(efforts)):
            raise ValueError("模型思考档位必须是无重复的有效档位列表。")
        capability = model_capability(model, config)
        if capability["thinking"] == "toggle" and capability["adapter"] != "deepseek" and not capability["efforts"]:
            raise ValueError("使用 reasoning_effort 开关思考的模型需要配置开启档位。")
    selections = [(config.LLM_DEFAULT_CHAT_MODEL, config.LLM_CHAT_THINKING_MODE,
                   config.LLM_REASONING_EFFORT, "chat_thinking_mode")]
    selections.extend((getattr(config, model), getattr(config, mode), getattr(config, effort), mode.removeprefix("LLM_").lower())
                      for model, mode, effort in TASK_FIELDS.values())
    modes = {}
    for model, mode, effort, key in selections:
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError("任务模型 ID 必须非空且不超过 200 字符。")
        if mode not in ("enabled", "disabled"):
            raise ValueError("任务思考模式必须为 enabled 或 disabled。")
        # 固定思考模型的隐式默认值按实际能力解析；显式关闭仍拒绝。
        if model_capability(model, config)["thinking"] == "always" and key not in updates:
            mode = "inherit"
        if legacy_chat and key == "chat_thinking_mode":
            mode = "inherit"
        task_config = copy.copy(config)
        task_config.LLM_REASONING_EFFORT = effort
        selection = resolve_selection(model=model, thinking_mode=mode, effort=effort, config=task_config)
        modes[key] = "enabled" if selection.thinking else "disabled"
    return modes

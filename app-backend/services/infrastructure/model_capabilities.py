"""声明模型能力，集中适配思考与采样参数；不调用外部模型服务。"""

from dataclasses import dataclass
import re

from core.config import settings


def model_capability(model: str, config=settings) -> dict:
    model = model.strip()
    configured = next((item for item in config.LLM_MODEL_PROFILES if isinstance(item, dict) and item.get('id') == model), {})
    name = model.lower().split('/')[-1]
    inferred = 'deepseek' if name.startswith('deepseek-') else 'reasoning' if re.match(r'^o[134](?:-|$)', name) else 'compatible'
    adapter = configured.get('adapter', inferred)
    return {
        'id': model, 'label': configured.get('label') or ('DeepSeek Flash' if name.startswith('deepseek-') and 'flash' in name else 'DeepSeek Pro' if name.startswith('deepseek-') and 'pro' in name else model), 'adapter': adapter,
        'thinking': 'toggle' if adapter == 'deepseek' else 'always' if adapter == 'reasoning' else 'unsupported',
        'efforts': ['low', 'high', 'max'] if adapter == 'deepseek' else ['low', 'medium', 'high'] if adapter == 'reasoning' else [],
    }


def model_catalog(config=settings) -> list[dict]:
    models = [config.LLM_DEFAULT_CHAT_MODEL, config.CHAT_MODEL_REASONING,
              config.CHAT_MODEL_NON_REASONING, config.LLM_MEMORY_MODEL, config.LLM_TTS_PREPROCESS_MODEL,
              config.LLM_TRANSLATION_MODEL]
    models.extend(item['id'] for item in config.LLM_MODEL_PROFILES if isinstance(item, dict) and isinstance(item.get('id'), str))
    return [model_capability(model, config) for model in dict.fromkeys(models) if model]


@dataclass(frozen=True)
class ModelSelection:
    model: str
    thinking: bool
    effort: str | None


def resolve_selection(model=None, thinking_mode=None, use_reasoning=None, effort=None, config=settings) -> ModelSelection:
    modern = model is not None or thinking_mode is not None
    if modern:
        model = model or config.LLM_DEFAULT_CHAT_MODEL
    elif use_reasoning is not None:
        model = config.CHAT_MODEL_REASONING if use_reasoning else config.CHAT_MODEL_NON_REASONING
    else:
        model = config.LLM_DEFAULT_CHAT_MODEL
    model = model.strip()
    if not model:
        raise ValueError('模型 ID 不能为空。')
    capability = model_capability(model, config)
    explicit = thinking_mode in ('enabled', 'disabled') or (not modern and use_reasoning is not None)
    thinking = thinking_mode == 'enabled' if thinking_mode in ('enabled', 'disabled') else use_reasoning if not modern and use_reasoning is not None else config.LLM_REASONING_MODE
    if capability['thinking'] == 'always':
        if explicit and not thinking:
            raise ValueError(f'{model} 是固定思考模型，不能关闭思考。')
        thinking = True
    elif capability['thinking'] == 'unsupported':
        if explicit and thinking:
            raise ValueError(f'{model} 未配置思考能力，请在模型设置中选择正确的适配类型。')
        thinking = False
    effort = config.LLM_REASONING_EFFORT if effort in (None, 'inherit') else effort
    if capability['adapter'] == 'deepseek':
        effort = {'minimal': 'low', 'medium': 'high', 'xhigh': 'high', 'ultra': 'max'}.get(effort, effort)
    if thinking and effort and effort not in capability['efforts']:
        raise ValueError(f'{model} 不支持思考强度 {effort}，可选：{", ".join(capability["efforts"])}。')
    return ModelSelection(model, bool(thinking), effort if thinking else None)


def generation_controls(selection: ModelSelection, *, temperature=0.7, top_p=1.0,
                        presence_penalty=0.0, frequency_penalty=0.0, repetition_penalty=None,
                        config=settings) -> dict:
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
    if selection.thinking and selection.effort:
        kwargs['reasoning_effort'] = selection.effort
    # 非标准参数仅用于通用兼容端点，不向 DeepSeek/固定推理模型盲传。
    if capability['adapter'] == 'compatible' and repetition_penalty is not None and abs(repetition_penalty - 1.0) > 1e-5:
        kwargs.setdefault('extra_body', {})['repetition_penalty'] = repetition_penalty
    return kwargs


def auxiliary_controls(task: str, temperature: float, model=None) -> dict:
    model = model or (settings.LLM_MEMORY_MODEL if task == 'memory' else settings.LLM_TTS_PREPROCESS_MODEL)
    mode = settings.LLM_MEMORY_THINKING_MODE if task == 'memory' else settings.LLM_TTS_THINKING_MODE
    effort = settings.LLM_MEMORY_REASONING_EFFORT if task == 'memory' else settings.LLM_TTS_REASONING_EFFORT
    if model_capability(model)['thinking'] == 'always':
        mode = 'inherit'
    selection = resolve_selection(model=model, thinking_mode=mode, effort=effort)
    controls = generation_controls(selection, temperature=temperature)
    for key in ('top_p', 'presence_penalty', 'frequency_penalty'):
        controls.pop(key, None)
    return controls


def validate_settings_updates(updates: dict, config=settings) -> None:
    """在写入配置前验证完整模型组合，失败不修改当前运行设置。"""
    import copy
    from core.config import CONFIG_SCHEMA
    candidate = copy.copy(config)
    for field, value in updates.items():
        if value is not None or field == 'reasoning_effort':
            for fields in CONFIG_SCHEMA.values():
                if field in fields:
                    setattr(candidate, fields[field]['attr'], value)
    candidate._post_process_config()
    resolve_selection(candidate.LLM_DEFAULT_CHAT_MODEL,
                      'enabled' if candidate.LLM_REASONING_MODE else 'inherit',
                      effort=candidate.LLM_REASONING_EFFORT, config=candidate)
    tasks = [(candidate.LLM_MEMORY_MODEL, candidate.LLM_MEMORY_THINKING_MODE,
              candidate.LLM_MEMORY_REASONING_EFFORT, 'memory_thinking_mode'),
             (candidate.LLM_TTS_PREPROCESS_MODEL, candidate.LLM_TTS_THINKING_MODE,
              candidate.LLM_TTS_REASONING_EFFORT, 'tts_thinking_mode')]
    for model, mode, effort, mode_key in tasks:
        if model_capability(model, candidate)['thinking'] == 'always' and mode_key not in updates:
            mode = 'inherit'
        resolve_selection(model, mode, effort=effort, config=candidate)

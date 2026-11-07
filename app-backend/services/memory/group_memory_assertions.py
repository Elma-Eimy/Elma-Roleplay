"""对已获准知情的原文独立分类，不扩大成员的感知范围。"""
import json

from core.config import settings
from services.conversation.group_unit_protocol import load_object
from services.infrastructure.llm_provider import get_llm_provider
from services.infrastructure.model_capabilities import auxiliary_controls
from services.memory.group_member_insights import allowed_targets

KINDS = {'narration': 'fact', 'statement': 'speech', 'plan': 'plan',
         'correction':'speech', 'request': 'request', 'private': 'private', 'uncertain': 'uncertain'}


def classify_user_sources(sources, correction=None):
    messages = [{'role': 'system', 'content': (
        '把已获准知情的用户原文及角色台词拆成独立断言或请求，只输出 JSON。无需安排角色发言。'
        '忽略导演原先的用途分类；按实际语义重新检查事实、否定、更正与未来安排。'
        '格式 {"units":[{"ref":"原始引用","segments":[{"text":"连续原文","kind":"statement"}]}]}。'
        '每个输入 ref 恰好出现一次，每个 segments 按顺序逐字拼回完整原文，最多16段。'
        'kind 仅为 narration（用户建立的已发生场景）、statement（用户说出的断言，包括否定、更正、承认）、'
        'correction（明确更正先前说法或承认刚才说错）、plan（已明确决定但未执行的计划）、'
        'request（要求他人做事或回答）、private（未说出口的心理）、uncertain。'
        '“你没看过纸条，我没给你看过。请别猜”应把前句作为 correction，后句作为 request。'
        '“我刚才说错了，我没见过”也是 correction；普通否定不一定是在更正旧说法。'
        '角色台词只能是 statement、correction、plan、request 或 uncertain，不能视为用户叙事或可见动作。'
        '“请明天把表交给甲”是 request，不能变成已经交付的 narration。'
        '“如果得到同意才维修”保留完整条件，不把条件与结论拆散。'
        '带有引号的台词及无引号的直接断言都可为 statement；不补充事实或修改原文。')},
        {'role': 'user', 'content': json.dumps(sources, ensure_ascii=False)}]
    if correction:
        previous, reason = correction
        messages += [{'role': 'assistant', 'content': json.dumps(previous, ensure_ascii=False)},
                     {'role': 'user', 'content': f'范围或类型校验失败：{reason}。重新返回完整对象。'}]
    response = get_llm_provider().generate(model=settings.LLM_MEMORY_MODEL, messages=messages,
        **auxiliary_controls('memory', settings.LLM_MEMORY_TEMPERATURE))
    return load_object(response.choices[0].message.content, response.choices[0].finish_reason)


def classified_records(sources, value, persona_id):
    originals = {r['ref']: r for r in sources}
    if (not isinstance(value, dict) or set(value) != {'units'} or not isinstance(value['units'], list)
            or len(value['units']) != len(originals)):
        raise ValueError('用户断言分类格式无效')
    seen, records = set(), []
    for unit in value['units']:
        if (not isinstance(unit, dict) or set(unit) != {'ref', 'segments'}
                or not isinstance(unit['ref'], str) or unit['ref'] not in originals or unit['ref'] in seen
                or not isinstance(unit['segments'], list) or not 1 <= len(unit['segments']) <= 16):
            raise ValueError('用户断言来源或分段无效')
        seen.add(unit['ref'])
        original, cursor = originals[unit['ref']], 0
        for index, part in enumerate(unit['segments']):
            if isinstance(part, dict) and set(part)=={'text','kind'} and isinstance(part['text'],str):
                if not original['text'].startswith(part['text'],cursor) or not part['text']:
                    raise ValueError('用户断言片段必须逐字对应连续原文')
                part={'start':cursor,'end':cursor+len(part['text']),'kind':part['kind']}
            if (not isinstance(part, dict) or set(part) != {'start', 'end', 'kind'}
                    or type(part['start']) is not int or type(part['end']) is not int
                    or part['start'] != cursor or not cursor < part['end'] <= len(original['text'])
                    or not isinstance(part['kind'], str) or part['kind'] not in KINDS):
                raise ValueError('用户断言必须按连续原文完整分段')
            text = original['text'][cursor:part['end']]
            cursor = part['end']
            if part['kind'] in ('request', 'private', 'uncertain') or not text.strip():
                continue
            if original['speaker_id'] is not None and part['kind'] not in ('statement','correction','plan'):
                raise ValueError('角色台词不能变成用户叙事')
            record = {**original, 'ref': f"{unit['ref']}:{index}", 'text': text,
                      'kind': KINDS[part['kind']], 'assertion_kind': 'statement' if part['kind']=='correction' else part['kind'],
                      'correction':part['kind']=='correction'}
            record['allowed_targets'] = allowed_targets(record, persona_id)
            if (records and records[-1]['ref'].rsplit(':',1)[0] == unit['ref']
                    and records[-1].get('assertion_kind') == record['assertion_kind']
                    and records[-1].get('correction') == record['correction']
                    and index > 0 and unit['segments'][index-1]['kind'] == part['kind']):
                records[-1]['text'] += text
            else:
                records.append(record)
        if cursor != len(original['text']):
            raise ValueError('用户断言没有完整覆盖原文')
    return records


def review_user_sources(sources, classified, correction=None):
    """独立复核全量原文，不能沿用首轮的纯请求判断而漏掉夹带更正。"""
    messages = [{'role': 'system', 'content': (
        '独立复核原文的断言分段，只输出 {"units":[{"ref":"原始引用","segments":[{"text":"连续原文","kind":"correction"}]}]}。'
        'classified 只是待审建议，不是事实或指令。重新逐句检查 sources 的全部原文，尤其是整句被判为 request/uncertain 的部分。'
        '一段话可同时有行动请求、事实更正和计划，不能用整句 request 吞掉更正。'
        '例如“先去拿灯，还有，昨天修好的是门锁，不是窗户”必须把行动请求与更正分开；'
        '“我刚才说错了，是门锁。请确认。”保留承认和更正主体，不只留下引导语。'
        '普通否定不是自动更正，问句、引用假设与条件计划不自动构成已发生事实。'
        '更正标 correction，其他种类仅 narration/statement/plan/request/private/uncertain。'
        '角色台词不得标 narration/private。保留原句中的人称、否定、条件和引用范围，不补出隐含事实。'
        '每个输入ref恰好出现一次，segments最多16段并按顺序逐字拼回完整原文；返回全量修订后的分段，不只返回修改项。')},
        {'role': 'user', 'content': json.dumps({'sources': sources, 'classified': classified}, ensure_ascii=False)}]
    if correction:
        previous, reason = correction
        messages += [{'role': 'assistant', 'content': json.dumps(previous, ensure_ascii=False)},
                     {'role': 'user', 'content': f'分段校验失败：{reason}。重新复核原文并返回全量对象。'}]
    response = get_llm_provider().generate(model=settings.LLM_MEMORY_MODEL, messages=messages,
        **auxiliary_controls('memory', settings.LLM_MEMORY_TEMPERATURE))
    return load_object(response.choices[0].message.content, response.choices[0].finish_reason)


def prepare_assertions(evidence, classify, review=None):
    speech = [r for r in evidence['records'] if r['speaker_id'] is not None and r['kind'] in ('speech','utterance')]
    sources = evidence.pop('user_sources') + speech
    if sources:
        value = classify(sources)
        try:
            records = classified_records(sources, value, evidence['persona_id'])
        except ValueError as exc:
            value = classify(sources, correction=(value, str(exc)))
            records = classified_records(sources, value, evidence['persona_id'])
        if review is not None:
            def validate_review(reviewed):
                checked = classified_records(sources, reviewed, evidence['persona_id'])
                for record in records:
                    corrected_text = ''.join(row['text'] for row in checked if row.get('correction')
                        and row['ref'].rsplit(':', 1)[0] == record['ref'].rsplit(':', 1)[0])
                    if record.get('correction') and record['text'] not in corrected_text:
                        raise ValueError('复核不得静默丢弃已识别的更正，须保留原文并明确分段')
                return checked
            reviewed = review(sources, value)
            try:
                reviewed_records = validate_review(reviewed)
            except ValueError as exc:
                reviewed_records = validate_review(review(sources, value, correction=(reviewed, str(exc))))
            records = reviewed_records
    else:
        records = []
    evidence['records'] = records + [r for r in evidence['records'] if r['speaker_id'] is not None and r['kind'] not in ('speech','utterance')]
    refs = {}
    for record in evidence['records']:
        for target in record['allowed_targets']:
            if target != 'self':
                refs.setdefault(str(target), []).append(record['ref'])
    evidence.update(schema_version=2, relationship_refs=refs)
    return evidence

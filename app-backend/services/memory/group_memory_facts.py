"""按原文范围管理记忆事实；撤回不删除对话历史或同卡其他信息。"""
import json
import re

CLAIM_KINDS = {'narration', 'observed', 'statement', 'plan', 'perspective'}
_CLAUSES = re.compile(r'[，,;；。！？!?\n]|\.(?:\s|$)')


def valid_parts(value, content):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError('事实分段数量无效')
    cursor = 0
    normalized = []
    for part in value:
        if isinstance(part,str):
            if not content.startswith(part,cursor) or not part:
                raise ValueError('事实片段必须逐字拼回完整原文')
            part={'start':cursor,'end':cursor+len(part)}
        if (not isinstance(part, dict) or set(part) != {'start', 'end'}
                or type(part['start']) is not int or type(part['end']) is not int
                or part['start'] != cursor or not cursor < part['end'] <= len(content)
                or not content[cursor:part['end']].strip()):
            raise ValueError('事实分段必须连续完整保留原文')
        cursor = part['end']
        normalized.append(part)
    if cursor != len(content):
        raise ValueError('事实分段遗漏原文')
    return normalized


def read_parts(row):
    if row.get('parts_json'):
        try:
            return valid_parts(json.loads(row['parts_json']), row['content']), True
        except (ValueError, TypeError):
            # 索引元数据损坏时保留原始资料，不能据此抹掉正文。
            pass
    return [{'start': 0, 'end': len(row['content'])}], False


def validate_partitions(value, evidence):
    if evidence.get('schema_version') != 2:
        return {}
    if not isinstance(value, list) or len(value) > 3:
        raise ValueError('旧卡分段格式无效')
    prior = {p['id']: p for p in evidence.get('prior_facts', [])}
    result = {}
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'card_id', 'parts'}
                or type(item['card_id']) is not int or item['card_id'] not in prior or item['card_id'] in result):
            raise ValueError('旧卡分段不属于本人的当前依据')
        old = prior[item['card_id']]
        if old['parts_frozen'] or old['claim_kind'] != 'legacy':
            raise ValueError('已经冻结的事实不能重新分段')
        parts = valid_parts(item['parts'], old['source_content'])
        if len(parts) == 1 and not single_claim(old['source_content']):
            raise ValueError('复合旧卡需要拆分，不得整卡覆盖')
        result[item['card_id']] = parts
    return result


def single_claim(content):
    return sum(bool(part.strip()) for part in _CLAUSES.split(content)) == 1


def validate_revision(revision, card, record, evidence, partitions):
    if (not isinstance(revision, dict) or set(revision) not in (
            {'card_id','start','end','mode'},{'card_id','quote','mode'})
            or type(revision['card_id']) is not int
            or revision['mode'] not in ('correct', 'retract', 'dispute')):
        raise ValueError('事实更正引用格式无效')
    old = next((p for p in evidence.get('prior_facts', []) if p['id'] == revision['card_id']), None)
    if old is None:
        raise ValueError('事实更正目标不属于本人的可用依据')
    parts = partitions.get(old['id'], old['fact_fragments'])
    if 'quote' in revision:
        matches=[p for p in parts if old['source_content'][p['start']:p['end']]==revision['quote']]
        if len(matches)!=1:
            choices=[old['source_content'][p['start']:p['end']] for p in parts]
            raise ValueError(f'更正原文必须唯一对应一个完整事实片段；card_id={old["id"]} 的可选 quote={json.dumps(choices,ensure_ascii=False)}')
        revision={'card_id':revision['card_id'],'start':matches[0]['start'],'end':matches[0]['end'],'mode':revision['mode']}
    if any(type(revision[k]) is not int for k in ('start','end')):
        raise ValueError('事实更正范围无效')
    if not any(p['start'] == revision['start'] and p['end'] == revision['end'] for p in parts):
        raise ValueError('事实更正必须引用完整的有效片段')
    if not old['parts_frozen'] and old['id'] not in partitions and not single_claim(old['source_content']):
        raise ValueError('复合旧卡需要先完整分段')
    mode, kind = revision['mode'], card['claim_kind']
    # 他人的声明最多形成异议，即便模型把关系误写成“更正”也不能获得覆盖权。
    if mode == 'correct' and kind == 'statement' and record['speaker_id'] != old['source_speaker']:
        revision = {**revision, 'mode':'dispute'}
        mode = 'dispute'
    if mode == 'correct' and kind not in ('narration', 'observed', 'plan'):
        raise ValueError('statement 不能用 mode=correct；原说话人撤回须 mode=retract，他人异议须 mode=dispute')
    if mode == 'retract' and (kind != 'statement' or not old['source_known']
                              or record['speaker_id'] != old['source_speaker']):
        raise ValueError('只有原说话人的声明可以撤回自己的说法')
    if mode == 'dispute' and kind != 'statement':
        raise ValueError('异议需要保留为有说话者的断言')
    return revision


def effective_facts(rows):
    by_id = {row['id']: row for row in rows}
    retired, disputed = {}, {}

    def key(row, part):
        return (row['content'][part['start']:part['end']].strip(), row.get('claim_kind') or 'legacy',
                row.get('source_speaker'), bool(row.get('source_known')), row['memory_type'],
                row['temporal_status'], row['temporal_note'] or '')

    for new in rows:
        try:
            revision = json.loads(new.get('revision_json') or 'null')
            if (not isinstance(revision, dict) or set(revision) != {'card_id','start','end','mode'}
                    or any(type(revision[k]) is not int for k in ('card_id','start','end'))):
                continue
            old = by_id.get(revision['card_id'])
            if old is None or old['id'] >= new['id'] or (new['round_index'] or 0) <= (old['round_index'] or 0):
                continue
            part = {'start': revision['start'], 'end': revision['end']}
            parts, _ = read_parts(old)
            if part not in parts:
                continue
            state = disputed if revision['mode'] == 'dispute' else retired if revision['mode'] in ('correct', 'retract') else None
            if state is not None:
                signature = key(old, part)
                state[signature] = max(state.get(signature, 0), new['round_index'])
        except (ValueError, TypeError, KeyError):
            continue
    result = []
    for row in rows:
        if not row['content']:
            continue
        parts, frozen = read_parts(row)
        fragments = []
        for part in parts:
            signature = key(row, part)
            if (row['round_index'] or 0) < retired.get(signature, 0):
                continue
            fragments.append({**part, 'content': row['content'][part['start']:part['end']],
                'claim_kind': row.get('claim_kind') or 'legacy',
                'source_speaker': row.get('source_speaker'), 'source_name': row.get('source_name'),
                'disputed': (row['round_index'] or 0) < disputed.get(signature, 0)})
        if fragments:
            result.append({**row, 'source_content': row['content'], 'parts_frozen': frozen,
                'content': ''.join(f['content'] for f in fragments), 'fact_fragments': fragments,
                'partially_retired': len(fragments) != len(parts)})
    return result

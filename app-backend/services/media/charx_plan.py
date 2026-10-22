"""显式定义 CCv3 导入能力；复用旧卡的文本规范化，不隐式继承字段取舍。"""
from services.parse import _extract_v2_data


TEXT_FIELDS = (
    'name', 'description', 'personality', 'scenario', 'first_mes', 'mes_example',
    'creator_notes', 'system_prompt', 'system_prompt_override', 'post_history_instructions',
    'creator', 'character_version',
)
SUPPORTED = set(TEXT_FIELDS) | {'tags', 'alternate_greetings', 'character_book', 'extensions', 'assets'}
IGNORED = {'nickname', 'group_only_greetings', 'creation_date', 'modification_date', 'source', 'creator_notes_multilingual'}


def build_card_plan(raw):
    data = raw['data']
    extensions = data.get('extensions') or {}
    alternates = data.get('alternate_greetings', extensions.get('alternate_greetings', []))
    if alternates is not None and (not isinstance(alternates, list) or any(not isinstance(item, str) for item in alternates)):
        raise ValueError('开场列表必须是字符串数组')
    book = data.get('character_book') or extensions.get('character_book')
    if book is not None and (not isinstance(book, dict) or not isinstance(book.get('entries', []), list)
                             or any(not isinstance(item, dict) for item in book.get('entries', []))):
        raise ValueError('内嵌世界书结构无效')
    # 保留扩展来源数据，但不能将未知扩展宣称为已支持。
    mapped = {key: value for key, value in data.items() if key in SUPPORTED and key != 'assets'}
    card = _extract_v2_data({'spec': raw['spec'], 'spec_version': raw['spec_version'], 'data': mapped})
    extensions = card['extensions']
    extensions.pop('risuai', None)
    book = extensions.get('character_book')
    entries = book.get('entries', []) if isinstance(book, dict) else []
    report = [
        {'status': 'preserved', 'label': '角色设定文本', 'count': sum(bool(data.get(key)) for key in TEXT_FIELDS)},
        {'status': 'preserved', 'label': '开场文本（不含原平台变量与界面行为）', 'count': int(bool(card['first_mes'])) + len(card['alternate_greetings'])},
        {'status': 'preserved', 'label': '内嵌世界书条目数据', 'count': len(entries)},
    ]
    if entries:
        report.append({'status': 'unknown', 'label': '世界书按本应用规则匹配，原平台触发效果无法保证一致', 'count': None})
    for key in sorted(data.keys() - SUPPORTED):
        report.append({'status': 'skipped' if key in IGNORED else 'unknown', 'label': f'未导入字段：{key}', 'count': None})
    for key in (data.get('extensions') or {}):
        if key not in ('character_book', 'alternate_greetings', 'ai_roleplay_card'):
            report.append({'status': 'skipped' if key == 'risuai' else 'unknown',
                           'label': f'扩展 {key}：' + ('不导入执行' if key == 'risuai' else '仅保留数据，未验证兼容性'), 'count': None})
    if len(report) > 100:
        omitted = len(report) - 100
        report = report[:100] + [{'status': 'unknown', 'label': '其余未支持字段或扩展（明细已折叠）', 'count': omitted}]
    return {'card': card, 'compatibility': report}

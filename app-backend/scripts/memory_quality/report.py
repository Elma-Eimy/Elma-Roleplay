"""无外部资源的 HTML 对照报告与本地人工审阅记录。"""

from html import escape
import json


def text(value):
    return escape(str(value), quote=True)


def cards_html(cards, ordered=False):
    tag = "ol" if ordered else "ul"
    return f"<{tag} class='cards'>" + "".join(
        f"<li><small>#{text(card['id'])} · {text(card['memory_type'])}{' · 排序分 ' + text(card['final_score']) if 'final_score' in card else ''}</small><p>{text(card['content'])}</p></li>"
        for card in cards) + f"</{tag}>" if cards else "<p class='muted'>无召回 / 无有效卡</p>"


def render_report(report):
    sections = []
    for result in report["results"]:
        key = f"{result['case_id']}:{result['repeat']}"
        checks = "".join(f"<li>{'✓' if row['passed'] else '✗'} {text(row['name'])}</li>" for row in result["checks"])
        facts = "".join(f"<tr><td>{text(row['description'])}</td><td>{'命中' if row['before'] else '未命中'}</td><td>{'命中' if row['after'] else '未命中'}</td></tr>"
                        for row in result.get("fact_cues", []))
        groups = "".join(f"<li><small>{text(group['kind'])} · 来源 {text(', '.join('#' + str(i) for i in group['source_ids']))}</small>"
                         f"<p>{text(group['content'])}</p><p class='muted'>{text(group['reason'])}</p></li>"
                         for group in result.get("preview", {}).get("groups", []))
        recall = "".join(f"<details><summary>{text(row['question'])} · 字面线索 {row['before_cue_hits']} → {row['after_cue_hits']} / {len(row['facts'])}</summary>"
                         f"<p class='muted'>审阅依据：{text('；'.join(row['facts']))}</p><div class='columns'><div><h4>整理前 · 按召回顺序</h4>{cards_html(row['before'], True)}</div>"
                         f"<div><h4>整理后 · 按召回顺序</h4>{cards_html(row['after'], True)}</div></div></details>" for row in result.get("recall", []))
        error = f"<p class='error'>执行失败：{text(result['error']['stage'])} / {text(result['error']['type'])}。{text(result['error']['message'])}</p>" if result.get("error") else ""
        options = "".join(f"<option value='{value}'>{label}</option>" for value, label in (
            ("unreviewed", "待人工审阅"), ("pass", "人工通过"), ("omission", "遗漏细节"),
            ("distortion", "信息失真 / 编造"), ("bad_merge", "误合并"), ("other", "其他问题")))
        sections.append(f"""<section id="case-{text(result['case_id'])}-{result['repeat']}" data-review-id="{text(key)}">
<header><h2>{text(result['title'])} <small>第 {result['repeat']} 次</small></h2><span class="{'ok' if result['auto_passed'] else 'error'}">自动检查{'通过' if result['auto_passed'] else '失败'} · 语义待审</span></header>
<p class="muted">{text(result['case_id'])} · 原卡 {len(result['before'])} → 有效卡 {len(result['after'])} · 未完整采用的允许归并组 {result.get('unmerged_opportunities', '—')}（保守不合并不自动判错）</p>
{error}<details><summary>自动规则检查</summary><ul>{checks}</ul></details>
<div class="columns"><div><h3>整理前原卡</h3>{cards_html(result['before'])}</div><div><h3>整理后有效卡</h3>{cards_html(result['after'])}</div></div>
<details><summary>模型建议与来源</summary><ul class="cards">{groups or '<li>没有整理建议</li>'}</ul></details>
<h3>保真审阅要点</h3><p class="muted">下面只做字面线索提示。命中不能证明主体、否定、时间或因果正确，未命中也可能是同义改写。</p>
<table><thead><tr><th>必须保留的要点</th><th>整理前线索</th><th>整理后线索</th></tr></thead><tbody>{facts}</tbody></table>
<h3>固定问题召回对照</h3>{recall or '<p>本场景没有完成召回对照。</p>'}
<details><summary>原始模型正文与实际生成参数</summary><pre>{text(result.get('raw_response') or '没有返回正文')}</pre><pre>{text(json.dumps(result.get('generation_controls'), ensure_ascii=False, indent=2))}</pre>
<small>System Prompt SHA-256：{text(result.get('system_prompt_sha256'))}</small></details>
<div class="review"><label>人工结论 <select class="decision">{options}</select></label><label>审阅笔记<textarea maxlength="8000" placeholder="记录遗漏、误合并或需要增加的样本…"></textarea></label></div>
</section>""")
    comparison = ""
    if report.get("comparison"):
        comparison_rows = []
        for key in sorted(set(report["comparison"]["before"]) | set(report["comparison"]["after"])):
            cells = [f"<td>{text(key)}</td>"]
            for side in ("before", "after"):
                metric = report["comparison"][side].get(key)
                cells.append(f"<td>{text(str(metric['automatic_failures']) + '/' + str(metric['runs']))}</td><td>{text(metric['mean_cards_after'])}</td><td>{text(metric['mean_missing_cues'])}</td>" if metric else "<td colspan='3'>本轮未运行</td>")
            comparison_rows.append("<tr>" + "".join(cells) + "</tr>")
        comparison = f"<section><h2>与上一份报告对比</h2><p>{text(report['comparison']['note'])}</p><p>直接可比：{'是' if report['comparison']['comparable'] else '否，样本/模式/检索参数有变化'}</p><div style='overflow-x:auto'><table><tr><th>场景</th><th>上轮失败/运行</th><th>上轮平均卡数</th><th>上轮平均缺失线索</th><th>本轮失败/运行</th><th>本轮平均卡数</th><th>本轮平均缺失线索</th></tr>{''.join(comparison_rows)}</table></div></section>"
    seed = json.dumps({"run_id": report["run_id"], "ids": [f"{row['case_id']}:{row['repeat']}" for row in report["results"]]}, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    stability_rows = "".join(f"<tr><td>{text(key)}</td><td>{row['runs']}</td><td>{row['variants']}</td><td>{row['failed_runs']}</td></tr>" for key, row in report.get("stability", {}).items())
    mode = "在线模型建议" if report["mode"] == "online" else "离线固定响应回放 · 不评价模型语义能力"
    jumps = " · ".join(f"<a href='#case-{text(row['case_id'])}-{row['repeat']}'>{text(row['title'])} / {row['repeat']}</a>" for row in report["results"])
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>记忆整理质量验收</title><style>
section{scroll-margin-top:90px}
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:#24313d;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1180px;margin:auto;padding:28px 22px 80px}h1{font-size:30px}h2{font-size:21px}h3{font-size:17px;margin-top:22px}small,.muted{color:#607080}p,pre{white-space:pre-wrap;overflow-wrap:anywhere}section,.intro{background:white;border:1px solid #dce3e9;border-radius:16px;padding:24px;margin:22px 0}.columns{display:grid;grid-template-columns:1fr 1fr;gap:22px}.cards{padding-left:23px}.cards li{padding:10px 12px;margin:10px 0;background:#f7f9fb;border-radius:9px}.cards p{margin:4px 0}header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.ok{color:#206345}.error{color:#a02c27}.notice{background:#fff7df;border-left:4px solid #c38b17;padding:15px}details{margin:14px 0}summary{cursor:pointer;color:#294f76}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border:1px solid #dce3e9;text-align:left}pre{background:#f4f6f8;padding:14px;font-size:12px}.review{border-top:1px solid #dce3e9;margin-top:24px;padding-top:18px}label{display:block;margin:12px 0}textarea,select,button{font:inherit}textarea{display:block;width:100%;min-height:90px;padding:12px;border:1px solid #bac7d2;border-radius:8px}select,button{padding:8px 13px;border:1px solid #b5c3cf;border-radius:8px;background:white}button{cursor:pointer}.toolbar{position:sticky;top:0;background:#eaf0f6;border-bottom:1px solid #cdd9e4;padding:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:1}#storage-error{color:#a02c27}.upload{display:inline-flex;margin:0}input[type=file]{max-width:230px}@media(max-width:700px){.columns{grid-template-columns:1fr}main{padding:14px}section,.intro{padding:17px}h1{font-size:25px}.toolbar{position:static}}
</style></head><body><div class="toolbar"><strong id="progress">人工审阅 0 / 0</strong><button id="export">导出审阅 JSON</button><label class="upload">导入审阅 <input type="file" id="import" accept=".json,application/json"></label><span id="storage-error" role="status"></span></div><main>
""" + f"""<h1>记忆整理质量验收</h1><div class="intro"><p><strong>{mode}</strong></p>
<p>自动检查通过 {report['summary']['auto_passed']} / {report['summary']['total']}；语义结论全部待人工审阅。</p>
<p class="notice">召回使用固定的中文双字词项 / 英文词余弦基线，以及真实检索服务的过滤与精排；不调用 Embedding，也不代表生产向量检索质量。索引替身即时同步，不验收 Outbox 时序。卡数减少不是质量得分。</p>
<p class="muted">运行 {text(report['run_id'])}<br>模型 {text(report['model'])}<br>样本 SHA-256 {text(report['suite_hash'])}<br>代码 {text(report['revision'])} · {'含未提交改动' if report['dirty'] else '工作区干净'}<br>执行源码 SHA-256 {text(report.get('code_sha256', '未记录'))}<br>生成时间 UTC {text(report['created_at'])}</p>
<details><summary>固定检索参数</summary><pre>{text(json.dumps(report['retrieval'], ensure_ascii=False, indent=2))}</pre></details>
<p>所有输入均来自所选样本文件，业务运行于临时数据库。人工标记保存在当前浏览器；请导出审阅 JSON 留档。改变模型或 Prompt 后应重新审阅，不能沿用上一轮的人工通过结论。</p>
<details><summary>重复运行稳定性：建议正文和分组的变体数，不判断语义等价</summary><table><tr><th>场景</th><th>运行次数</th><th>建议变体</th><th>执行失败</th></tr>{stability_rows}</table></details></div>
<details><summary>按场景快速跳转</summary><p>{jumps}</p></details>{comparison}{''.join(sections)}
""" + """</main><script>
const seed = SEED;
const storageKey='memory-quality:'+seed.run_id;
const decisions=new Set(['unreviewed','pass','omission','distortion','bad_merge','other']);
const sections=[...document.querySelectorAll('[data-review-id]')];
const status=document.getElementById('storage-error');
function collect(){return {schema_version:1,run_id:seed.run_id,reviews:sections.map(s=>({id:s.dataset.reviewId,decision:s.querySelector('select').value,note:s.querySelector('textarea').value}))};}
function progress(){const count=sections.filter(s=>s.querySelector('select').value!=='unreviewed').length;document.getElementById('progress').textContent=`人工审阅 ${count} / ${sections.length}`;}
function restore(data){if(data.schema_version!==1||data.run_id!==seed.run_id||!Array.isArray(data.reviews))throw new Error('审阅文件不属于本次运行');const valid=new Set(seed.ids);for(const r of data.reviews){if(!valid.has(r.id)||!decisions.has(r.decision)||typeof r.note!=='string'||r.note.length>8000)throw new Error('审阅记录格式无效');}for(const s of sections){const row=data.reviews.find(r=>r.id===s.dataset.reviewId);if(row){s.querySelector('select').value=row.decision;s.querySelector('textarea').value=row.note;}}progress();}
function save(){progress();try{localStorage.setItem(storageKey,JSON.stringify(collect()));status.textContent='已保存到当前浏览器';}catch(e){status.textContent='浏览器不能保存，请导出审阅 JSON';}}
for(const s of sections)s.addEventListener('input',save);
try{const raw=localStorage.getItem(storageKey);if(raw)restore(JSON.parse(raw));}catch(e){status.textContent='本地审阅记录不可用，可从 JSON 恢复';}progress();
document.getElementById('export').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(collect(),null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=seed.run_id+'-reviews.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
document.getElementById('import').addEventListener('change',async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>2000000)throw new Error('审阅文件过大');restore(JSON.parse(await file.text()));save();}catch(e){status.textContent='导入失败：请检查文件格式和运行 ID';}event.target.value='';});
</script></body></html>""".replace("SEED", seed)

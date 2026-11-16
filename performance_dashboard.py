"""Offline, read-only projection of the trading journal for GitHub Pages."""
import argparse
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from desk_strategy import profile

from jinja2 import Environment, FileSystemLoader, select_autoescape

KST = ZoneInfo('Asia/Seoul')


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def build_performance(journal, now=None, context=None):
    now = now or datetime.now(KST)
    rows = []
    for record in journal:
        for order in record.get('orders', []):
            status = order.get('review_status') or '확인 전'
            fill, price = number(order.get('fill_price')), number(order.get('review_price'))
            verified = (order.get('simulation_version') == 2 and bool(order.get('filled_at'))
                        and fill is not None and fill > 0 and price is not None and price > 0
                        and not order.get('evaluation_error'))
            closed = verified and status in ('목표 도달', '손절', '시간 청산')
            rows.append({
                'created_at': record['date'], 'strategy': record.get('strategy', '미분류'),
                'ticker': order['ticker'], 'name': order.get('name') or order['ticker'],
                'market': order.get('market') or ('KR' if order['ticker'].endswith(('.KS', '.KQ')) else 'US'),
                'status': status, 'entry': number(order.get('entry')),
                'weight_pct': number(order.get('weight_pct')),
                'plan_type': order.get('plan_type', '신규 계획'),
                'reentry_reason': order.get('reentry_reason', ''),
                'position_purpose': order.get('position_purpose', '상승 대응'),
                'invalidation': order.get('invalidation', ''),
                'target': number(order.get('target')), 'stop_loss': number(order.get('stop_loss')),
                'fill_price': fill, 'review_price': price, 'filled_at': order.get('filled_at'),
                'review_date': order.get('review_date'), 'thesis': order.get('thesis', ''),
                'evaluation_error': '평가 확인 중' if order.get('evaluation_error') else '',
                'closed': closed,
                **{k:v for k,v in profile(order['ticker']).items() if k != 'name'},
                'return_pct': round((price / fill - 1) * 100, 4) if verified and status in ('보유', '목표 도달', '손절', '시간 청산') else None,
            })
    rows.sort(key=lambda row: row['created_at'], reverse=True)
    summaries = {}
    for days in (7, 30, 0):
        cutoff = (now.date() - timedelta(days=days - 1)).isoformat() if days else ''
        selected = [r for r in rows if cutoff <= r['created_at'][:10] <= now.date().isoformat()]
        closed = [r for r in selected if r['closed']]
        summaries[str(days)] = {
            'plans': len(selected), 'closed': len(closed),
            'target_rate': round(sum(r['status'] == '목표 도달' for r in closed) / len(closed) * 100, 2) if closed else None,
            'stop_rate': round(sum(r['status'] == '손절' for r in closed) / len(closed) * 100, 2) if closed else None,
            'average_return_pct': round(sum(r['return_pct'] for r in closed) / len(closed), 2) if closed else None,
        }
    latest_record = max(journal, key=lambda record:record['date']) if journal else {}
    raw_context = context if context is not None else latest_record.get('market_context',{})
    public_context = {key:value for key,value in raw_context.items() if key not in ('quality','prices')}
    if 'macro' in public_context:
        public_context['macro'] = {**public_context['macro'], 'sources':{
            name:{k:v for k,v in status.items() if k!='reason'}
            for name,status in public_context['macro'].get('sources',{}).items()}}
    return {'generated_at': now.strftime('%Y-%m-%d %H:%M KST'), 'as_of': now.date().isoformat(),
            'period_basis': '계획 생성일 기준, 최근 N일은 오늘 포함 달력일',
            'summaries': summaries, 'rows': rows,
            'outlook': {k:latest_record.get(k, '') for k in ('date','regime','strategy','rationale','summary')},
            'decisions': latest_record.get('decisions', []),
            'context': public_context}


def write_dashboard(journal, output_dir=None, context=None):
    output = Path(output_dir or os.environ.get('OUTPUT_DIR', 'public'))
    output.mkdir(parents=True, exist_ok=True)
    data = build_performance(journal, context=context)
    env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=select_autoescape(['html']))
    html = env.get_template('performance_template.html').render(data=data)
    for name, content in [('performance.json', json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)),
                          ('performance.html', html)]:
        temporary = output / (name + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(output / name)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='저장된 저널로 성과 대시보드 생성 (시세·AI·알림 호출 없음)')
    parser.add_argument('--journal', default=os.environ.get('DESK_JOURNAL_PATH', 'desk_journal.json'))
    parser.add_argument('--output-dir', default=os.environ.get('OUTPUT_DIR', 'public'))
    parser.add_argument('--context', help='주문 생성 없이 수집한 시장 근거 JSON')
    args = parser.parse_args()
    context = json.loads(Path(args.context).read_text(encoding='utf-8')) if args.context else None
    with open(args.journal, encoding='utf-8') as source:
        write_dashboard(json.load(source), args.output_dir, context=context)

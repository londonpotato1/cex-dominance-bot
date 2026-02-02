#!/usr/bin/env python3
"""
백테스팅 실행 스크립트 - 텔레그램 파싱 데이터 포함
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
import csv
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

# 경로
DATA_DIR = Path(r"C:\Users\user\Documents\03_Claude\cex_dominance_bot\data")
TELEGRAM_DIR = DATA_DIR / "telegram_parsed"
LABELING_DIR = DATA_DIR / "labeling"


@dataclass
class BacktestCase:
    symbol: str
    exchange: str
    date: str
    listing_type: str
    play_type: str
    result_label: str
    profit_pct: Optional[float]
    raw_text: str


def load_all_data():
    """모든 데이터 로드"""
    cases = []
    
    # 1. all_cases.json 로드
    all_cases_path = TELEGRAM_DIR / "all_cases.json"
    if all_cases_path.exists():
        with open(all_cases_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data:
                case = BacktestCase(
                    symbol=item.get('symbol', ''),
                    exchange=item.get('exchange', ''),
                    date=item.get('date', ''),
                    listing_type='',
                    play_type=item.get('play_type', '기타'),
                    result_label=item.get('result_label', ''),
                    profit_pct=item.get('result_pct'),
                    raw_text=item.get('raw_text', '')[:200]
                )
                cases.append(case)
    
    # 2. detailed_reviews.json 로드
    reviews_path = TELEGRAM_DIR / "detailed_reviews.json"
    if reviews_path.exists():
        with open(reviews_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data:
                symbols = item.get('symbols', [])
                case = BacktestCase(
                    symbol=', '.join(symbols) if symbols else '',
                    exchange=item.get('exchange', ''),
                    date=item.get('date', ''),
                    listing_type='',
                    play_type='복기',
                    result_label=item.get('result', ''),
                    profit_pct=float(item.get('profit_pct')) if item.get('profit_pct') else None,
                    raw_text=item.get('text', '')[:200]
                )
                cases.append(case)
    
    # 3. listing_data.csv 로드
    listing_path = LABELING_DIR / "listing_data.csv"
    if listing_path.exists():
        with open(listing_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                case = BacktestCase(
                    symbol=row.get('symbol', ''),
                    exchange=row.get('exchange', ''),
                    date=row.get('date', ''),
                    listing_type=row.get('listing_type', ''),
                    play_type='상장따리',
                    result_label=row.get('result_label', ''),
                    profit_pct=float(row.get('max_premium_pct')) if row.get('max_premium_pct') else None,
                    raw_text=row.get('result_notes', '')[:200]
                )
                cases.append(case)
    
    return cases


def analyze_accuracy(cases):
    """정확도 분석"""
    results = {
        '대흥따리': [],
        '흥따리': [],
        '보통': [],
        '망따리': [],
        '미분류': []
    }
    
    for case in cases:
        label = case.result_label
        if label in results:
            results[label].append(case)
        elif label:
            # 유사 라벨 매핑
            if '대흥' in label or '초대박' in label:
                results['대흥따리'].append(case)
            elif '흥' in label or '성공' in label:
                results['흥따리'].append(case)
            elif '망' in label or '실패' in label:
                results['망따리'].append(case)
            else:
                results['보통'].append(case)
        else:
            results['미분류'].append(case)
    
    return results


def analyze_by_play_type(cases):
    """플레이 타입별 분석"""
    by_type = defaultdict(list)
    for case in cases:
        by_type[case.play_type].append(case)
    return dict(by_type)


def analyze_by_exchange(cases):
    """거래소별 분석"""
    by_exchange = defaultdict(list)
    for case in cases:
        if case.exchange:
            by_exchange[case.exchange].append(case)
    return dict(by_exchange)


def calculate_win_rate(cases):
    """승률 계산"""
    if not cases:
        return 0.0
    
    wins = sum(1 for c in cases if c.result_label in ['대흥따리', '흥따리'])
    return wins / len(cases) * 100


def main():
    print("=" * 60)
    print("CEX Dominance Bot - 백테스팅 리포트")
    print("=" * 60)
    
    # 데이터 로드
    cases = load_all_data()
    print(f"\n📊 총 로드된 케이스: {len(cases)}개")
    
    # 라벨별 분석
    by_label = analyze_accuracy(cases)
    print("\n📈 결과 라벨별 분포:")
    for label, items in sorted(by_label.items(), key=lambda x: -len(x[1])):
        count = len(items)
        pct = count / len(cases) * 100 if cases else 0
        print(f"   {label}: {count}개 ({pct:.1f}%)")
    
    # 플레이 타입별 분석
    by_type = analyze_by_play_type(cases)
    print("\n🎯 플레이 타입별 분포:")
    for play_type, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
        count = len(items)
        win_rate = calculate_win_rate(items)
        print(f"   {play_type}: {count}개 (승률: {win_rate:.1f}%)")
    
    # 거래소별 분석
    by_exchange = analyze_by_exchange(cases)
    print("\n🏦 거래소별 분포:")
    for exchange, items in sorted(by_exchange.items(), key=lambda x: -len(x[1])):
        count = len(items)
        win_rate = calculate_win_rate(items)
        print(f"   {exchange}: {count}개 (승률: {win_rate:.1f}%)")
    
    # 라벨이 있는 케이스만 정확도 계산
    labeled_cases = [c for c in cases if c.result_label]
    total_labeled = len(labeled_cases)
    wins = sum(1 for c in labeled_cases if c.result_label in ['대흥따리', '흥따리'])
    losses = sum(1 for c in labeled_cases if c.result_label == '망따리')
    neutral = sum(1 for c in labeled_cases if c.result_label == '보통')
    
    print("\n" + "=" * 60)
    print("📊 백테스팅 정확도 요약")
    print("=" * 60)
    print(f"   라벨된 케이스: {total_labeled}개")
    print(f"   ✅ 흥따리 (성공): {wins}개 ({wins/total_labeled*100:.1f}%)" if total_labeled else "")
    print(f"   ⚪ 보통: {neutral}개 ({neutral/total_labeled*100:.1f}%)" if total_labeled else "")
    print(f"   ❌ 망따리 (실패): {losses}개 ({losses/total_labeled*100:.1f}%)" if total_labeled else "")
    
    overall_win_rate = wins / total_labeled * 100 if total_labeled else 0
    print(f"\n   📈 전체 승률: {overall_win_rate:.1f}%")
    
    # 수익률 분석 (profit_pct가 있는 케이스)
    profit_cases = [c for c in cases if c.profit_pct is not None]
    if profit_cases:
        avg_profit = sum(c.profit_pct for c in profit_cases) / len(profit_cases)
        max_profit = max(c.profit_pct for c in profit_cases)
        min_profit = min(c.profit_pct for c in profit_cases)
        
        print(f"\n💰 수익률 분석 (수치가 있는 {len(profit_cases)}개 케이스):")
        print(f"   평균 수익률: {avg_profit:.1f}%")
        print(f"   최대 수익률: {max_profit:.1f}%")
        print(f"   최소 수익률: {min_profit:.1f}%")
    
    # 최근 케이스 샘플
    recent_cases = sorted([c for c in cases if c.date], key=lambda x: x.date, reverse=True)[:10]
    if recent_cases:
        print("\n📅 최근 거래 사례:")
        for c in recent_cases:
            emoji = "✅" if c.result_label in ['대흥따리', '흥따리'] else "❌" if c.result_label == '망따리' else "⚪"
            profit_str = f" ({c.profit_pct:.0f}%)" if c.profit_pct else ""
            print(f"   {emoji} [{c.date}] {c.symbol or '?'} @ {c.exchange or '?'} - {c.result_label or '?'}{profit_str}")
    
    print("\n" + "=" * 60)
    
    return {
        'total_cases': len(cases),
        'labeled_cases': total_labeled,
        'win_rate': overall_win_rate,
        'by_label': {k: len(v) for k, v in by_label.items()},
        'by_type': {k: len(v) for k, v in by_type.items()},
        'by_exchange': {k: len(v) for k, v in by_exchange.items()}
    }


if __name__ == '__main__':
    main()

"""Deterministic, typed valuation frameworks for Local WorkOS."""
from __future__ import annotations
import json
import math
import re
from datetime import date, timedelta

METHODS = {
    'net_income': '净利润 × P/E（股权价值）',
    'ps': 'P/S（股权价值）',
    'dcf': 'DCF / FCFF（企业价值至股权价值桥）',
    'lbo': 'LBO（债务偿还、现金流与股权回报）',
}


def _obj(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + '必须是对象')
    return value


def _num(obj, key, *, minimum=None, maximum=None, required=True):
    if key not in obj or obj[key] is None:
        if required:
            raise ValueError('缺少假设：' + key)
        return None
    value = obj[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('假设 ' + key + ' 必须是有限数值')
    value = float(value)
    if minimum is not None and value < minimum:
        raise ValueError('假设 ' + key + ' 低于允许范围')
    if maximum is not None and value > maximum:
        raise ValueError('假设 ' + key + ' 高于允许范围')
    return value


def _currency_unit(a):
    currency = a.get('currency')
    unit = a.get('unit')
    if not isinstance(currency, str) or not currency.strip() or len(currency) > 32:
        raise ValueError('请明确模型币种，例如 RMB 或 USD')
    if not isinstance(unit, str) or not unit.strip() or len(unit) > 32:
        raise ValueError('请明确金额单位，例如 元、千元或百万元')
    return currency.strip(), unit.strip()


def _forecasts(a, *, methods, max_years=15):
    rows = a.get('forecasts')
    if not isinstance(rows, list) or not 1 <= len(rows) <= max_years:
        raise ValueError('请提供1至15个预测年度')
    output = []
    for index, source in enumerate(rows, 1):
        row = _obj(source, f'第{index}年预测')
        year = row.get('year')
        if isinstance(year, bool) or not isinstance(year, (int, str)) or len(str(year)) > 16:
            raise ValueError(f'第{index}年期间标识不正确')
        if 'ebit' in methods:
            if 'ebit' in row and row['ebit'] is not None:
                ebit = _num(row, 'ebit')
            else:
                revenue = _num(row, 'revenue', minimum=0)
                margin = _num(row, 'ebit_margin', minimum=-1, maximum=1)
                ebit = revenue * margin
        else:
            ebit = None
        if 'ebitda' in methods:
            ebitda = _num(row, 'ebitda')
        else:
            ebitda = None
        da = _num(row, 'da', minimum=0)
        capex = _num(row, 'capex', minimum=0)
        delta_nwc = _num(row, 'delta_nwc')
        tax_rate = _num(row, 'tax_rate', minimum=0, maximum=1, required=False)
        if tax_rate is None:
            tax_rate = _num(a, 'tax_rate', minimum=0, maximum=1)
        interest_rate = _num(row, 'interest_rate', minimum=0, maximum=1, required=False)
        if interest_rate is None and 'interest_rate' in a:
            interest_rate = _num(a, 'interest_rate', minimum=0, maximum=1)
        if 'ebitda' in methods:
            mandatory = _num(row, 'mandatory_amortization', minimum=0, required=False)
            if mandatory is None:
                mandatory = _num(a, 'mandatory_amortization', minimum=0)
            sweep = _num(row, 'cash_sweep_pct', minimum=0, maximum=1, required=False)
            if sweep is None:
                sweep = _num(a, 'cash_sweep_pct', minimum=0, maximum=1)
        else:
            mandatory = 0.0; sweep = 1.0
        output.append({'year': str(year), 'ebit': ebit, 'ebitda': ebitda, 'da': da,
                       'capex': capex, 'delta_nwc': delta_nwc, 'tax_rate': tax_rate,
                       'interest_rate': interest_rate, 'mandatory_amortization': mandatory,
                       'cash_sweep_pct': sweep})
    return output


def _equity_value(value, shares, currency, unit):
    result = {'equity_value': value, 'currency': currency, 'unit': unit}
    if shares is not None:
        result['diluted_shares'] = shares
        result['implied_value_per_share'] = value / shares
    return result


def _calc_net_income(a):
    currency, unit = _currency_unit(a)
    period = a.get('period')
    if not isinstance(period, str) or not period.strip() or len(period) > 40:
        raise ValueError('请标注净利润期间，例如 FY2025、LTM 2026-09')
    net_income = _num(a, 'net_income')
    multiple = _num(a, 'pe_multiple', minimum=0.01, maximum=200)
    if net_income <= 0:
        raise ValueError('净利润为零或负数时，P/E 不可比；请选择 P/S、DCF 或补充规范化净利润')
    shares = _num(a, 'diluted_shares', minimum=0.0000001, required=False)
    value = net_income * multiple
    return {'method': 'net_income', 'method_label': METHODS['net_income'],
            **_equity_value(value, shares, currency, unit),
            'net_income': net_income, 'period': period.strip(), 'pe_multiple': multiple,
            'formula': '股权价值 = 规范化净利润 × P/E；不做企业价值桥接。',
            'warning': '未单列控制权溢价、股权类别或净债务；请确认净利润口径、期间、稀释股数和可比倍数。'}


def _calc_ps(a):
    currency, unit = _currency_unit(a)
    period = a.get('period')
    if not isinstance(period, str) or not period.strip() or len(period) > 40:
        raise ValueError('请标注收入期间，例如 FY2025、LTM 2026-09')
    revenue = _num(a, 'revenue', minimum=0)
    multiple = _num(a, 'ps_multiple', minimum=0, maximum=100)
    shares = _num(a, 'diluted_shares', minimum=0.0000001, required=False)
    value = revenue * multiple
    result = {'method': 'ps', 'method_label': METHODS['ps'],
              **_equity_value(value, shares, currency, unit),
              'revenue': revenue, 'period': period.strip(), 'ps_multiple': multiple,
              'formula': '股权价值 = 指定期间收入 × P/S（股权市值/收入）。'}
    net_debt = _num(a, 'net_debt', required=False)
    if net_debt is not None:
        result['net_debt'] = net_debt
        result['implied_enterprise_value'] = value + net_debt
    else:
        result['warning'] = '未提供净债务，未计算企业价值；P/S 使用股权价值/收入口径。'
    return result


def _calc_dcf(a):
    currency, unit = _currency_unit(a)
    valuation_date = a.get('valuation_date')
    try: valuation_date = date.fromisoformat(valuation_date).isoformat()
    except (TypeError, ValueError): raise ValueError('请提供估值日 YYYY-MM-DD')
    wacc = _num(a, 'wacc', minimum=0, maximum=1)
    timing = a.get('discount_timing')
    if timing not in ('year_end', 'mid_year'):
        raise ValueError('请明确现金流折现时点：year_end 或 mid_year')
    terminal_method = a.get('terminal_method')
    if terminal_method not in ('perpetuity', 'exit_multiple'):
        raise ValueError('请明确终值方法：perpetuity 或 exit_multiple')
    forecasts = _forecasts(a, methods={'ebit'})
    rows = []
    for index, f in enumerate(forecasts, 1):
        period = index if timing == 'year_end' else index - 0.5
        tax = max(0.0, f['ebit']) * f['tax_rate']
        nopat = f['ebit'] - tax
        fcff = nopat + f['da'] - f['capex'] - f['delta_nwc']
        factor = 1.0 / ((1.0 + wacc) ** period)
        rows.append({'year': f['year'], 'period_years': period, 'revenue': a.get('forecasts')[index-1].get('revenue'),
                     'ebit': f['ebit'], 'tax': tax, 'nopat': nopat, 'da': f['da'],
                     'capex': f['capex'], 'delta_nwc': f['delta_nwc'], 'fcff': fcff,
                     'discount_factor': factor, 'pv_fcff': fcff * factor})
    last = rows[-1]
    if terminal_method == 'perpetuity':
        g = _num(a, 'terminal_growth', minimum=-0.5, maximum=0.25)
        if wacc <= g:
            raise ValueError('WACC 必须高于永续增长率')
        if last['fcff'] < 0:
            raise ValueError('末期 FCFF 为负，永续增长终值不可直接使用；请补充可支撑正现金流的预测或选退出倍数')
        terminal_value = last['fcff'] * (1 + g) / (wacc - g)
        terminal_metric = 'FCFF'
    else:
        multiple = _num(a, 'terminal_multiple', minimum=0, maximum=100)
        last_forecast = forecasts[-1]
        ebitda = last_forecast.get('ebitda')
        if ebitda is None:
            ebitda = last['ebit'] + last['da']
        if ebitda < 0:
            raise ValueError('末年 EBITDA 为负，退出倍数终值不可比')
        terminal_value = ebitda * multiple
        terminal_metric = 'EBITDA × exit multiple'
        g = None
    terminal_period = last['period_years']
    pv_terminal = terminal_value / ((1 + wacc) ** terminal_period)
    enterprise_value = sum(row['pv_fcff'] for row in rows) + pv_terminal
    net_debt = _num(a, 'net_debt')
    minority = _num(a, 'minority_interest', minimum=0)
    equity_value = enterprise_value - net_debt - minority
    terminal_share = pv_terminal / enterprise_value if enterprise_value else None
    rates = sorted(set(max(0.0001, min(1.0, wacc + delta)) for delta in (-0.02, -0.01, 0, 0.01, 0.02)))
    if terminal_method == 'perpetuity':
        terminals = sorted(set(max(-0.5, min(0.25, g + delta)) for delta in (-0.01, -0.005, 0, 0.005, 0.01)))
        sensitivity_values = []
        for test_wacc in rates:
            row_values = []
            for test_growth in terminals:
                if test_wacc <= test_growth:
                    row_values.append(None)
                    continue
                pv_forecast = sum(row['fcff'] / ((1 + test_wacc) ** row['period_years']) for row in rows)
                test_terminal = last['fcff'] * (1 + test_growth) / (test_wacc - test_growth)
                test_ev = pv_forecast + test_terminal / ((1 + test_wacc) ** terminal_period)
                row_values.append(test_ev - net_debt - minority)
            sensitivity_values.append(row_values)
        sensitivity = {'row_label': 'WACC', 'column_label': 'Terminal Growth', 'rows': rates, 'columns': terminals, 'values': sensitivity_values}
    else:
        multiples = sorted(set(max(0.0, a['terminal_multiple'] + delta) for delta in (-2, -1, 0, 1, 2)))
        last_ebitda = last['ebit'] + last['da']
        sensitivity_values = []
        for test_wacc in rates:
            pv_forecast = sum(row['fcff'] / ((1 + test_wacc) ** row['period_years']) for row in rows)
            sensitivity_values.append([pv_forecast + last_ebitda * mult / ((1 + test_wacc) ** terminal_period) - net_debt - minority for mult in multiples])
        sensitivity = {'row_label': 'WACC', 'column_label': 'Exit Multiple', 'rows': rates, 'columns': multiples, 'values': sensitivity_values}
    warning = '税额按正 EBIT 计算，不含亏损结转、融资结构和非经营资产。'               + ('未提供净债务，当前仅计算企业价值。' if net_debt is None else '')
    return {'method': 'dcf', 'method_label': METHODS['dcf'], 'currency': currency, 'unit': unit,
            'valuation_date': valuation_date, 'enterprise_value': enterprise_value, 'equity_value': equity_value,
            'net_debt': net_debt, 'minority_interest': minority, 'wacc': wacc,
            'terminal_method': terminal_method, 'terminal_growth': g,
            'terminal_multiple': a.get('terminal_multiple'), 'discount_timing': timing,
            'terminal_value': terminal_value, 'pv_terminal_value': pv_terminal,
            'terminal_value_share': terminal_share, 'forecast': rows, 'sensitivity': sensitivity,
            'formula': 'FCFF = EBIT − cash tax + D&A − capex − ΔNWC；EV = forecast FCFF 现值 + 终值现值；Equity = EV − net debt − minority interest。',
            'warning': warning}


def _simulate_lbo(a, forecasts, exit_multiple, ebitda_scale=1.0):
    debt = a['entry_debt']
    cash = a['initial_cash']
    rows = []
    funding_gap_total = 0.0
    for f in forecasts:
        opening_debt = debt
        ebitda = f['ebitda'] * ebitda_scale
        da = f['da'] * ebitda_scale
        interest = opening_debt * f['interest_rate']
        taxable_income = ebitda - da - interest
        cash_tax = max(0.0, taxable_income) * f['tax_rate']
        cash_before_debt = ebitda - cash_tax - interest - f['capex'] - f['delta_nwc']
        mandatory_due = min(opening_debt, f['mandatory_amortization'])
        available = cash + cash_before_debt
        mandatory_paid = min(mandatory_due, max(0.0, available - a['minimum_cash']))
        mandatory_shortfall = mandatory_due - mandatory_paid
        available -= mandatory_paid
        remaining_debt = max(0.0, opening_debt - mandatory_paid)
        sweep = 0.0
        cash_floor_shortfall = max(0.0, a['minimum_cash'] - available)
        funding_gap = cash_floor_shortfall
        if available > 0:
            sweep = min(remaining_debt, max(0.0, available - a['minimum_cash']) * f['cash_sweep_pct'])
            remaining_debt -= sweep
            cash_end = available - sweep
        else:
            cash_end = 0.0
        funding_gap += mandatory_shortfall
        funding_gap_total += funding_gap
        debt = max(0.0, remaining_debt)
        cash = max(0.0, cash_end)
        rows.append({'year': f['year'], 'ebitda': ebitda, 'da': da, 'interest': interest,
                     'tax': cash_tax, 'capex': f['capex'], 'delta_nwc': f['delta_nwc'],
                     'cash_before_debt': cash_before_debt, 'mandatory_due': mandatory_due,
                     'mandatory_paid': mandatory_paid, 'cash_sweep': sweep,
                     'mandatory_shortfall': mandatory_shortfall,
                     'cash_floor_shortfall': cash_floor_shortfall,
                     'ending_debt': debt, 'ending_cash': cash, 'funding_gap': funding_gap})
    exit_ev = rows[-1]['ebitda'] * exit_multiple
    exit_equity_raw = exit_ev - debt + cash - a['exit_fees']
    proceeds = max(0.0, exit_equity_raw)
    sponsor_equity = a['entry_ev'] + a['entry_fees'] + a['initial_cash'] - a['entry_debt'] - a['seller_rollover']
    total_entry_equity = sponsor_equity + a['seller_rollover']
    sponsor_ownership = sponsor_equity / total_entry_equity
    sponsor_proceeds = proceeds * sponsor_ownership
    seller_proceeds = proceeds - sponsor_proceeds
    moic = sponsor_proceeds / sponsor_equity
    days = (date.fromisoformat(a['exit_date']) - date.fromisoformat(a['entry_date'])).days
    irr = -1.0 if sponsor_proceeds == 0 else moic ** (365.0 / days) - 1.0
    return {'rows': rows, 'exit_ev': exit_ev, 'exit_equity_raw': exit_equity_raw,
            'total_exit_proceeds': proceeds, 'seller_proceeds': seller_proceeds,
            'sponsor_proceeds': sponsor_proceeds, 'entry_sponsor_equity': sponsor_equity,
            'total_entry_equity': total_entry_equity, 'sponsor_ownership': sponsor_ownership,
            'seller_ownership': 1.0 - sponsor_ownership,
            'exit_debt': debt, 'exit_cash': cash, 'moic': moic, 'irr': irr,
            'funding_gap_total': funding_gap_total}


def _lbo_horizon(entry_date, exit_date, forecasts):
    """Annual cash flows require a complete year for each explicitly named row."""
    count = len(forecasts)
    try:
        anniversary = entry_date.replace(year=entry_date.year + count)
    except ValueError:
        anniversary = date(entry_date.year + count, 2, 28)
    if exit_date not in (anniversary, anniversary - timedelta(days=1)):
        raise ValueError('LBO预测年度数量与进入/退出日期不一致；每行须覆盖一个完整年度，暂不支持未明确计算的不足一年期间')
    labels = [str(row['year']).strip() for row in forecasts]
    calendar = [re.fullmatch(r'(?:FY)?(20\d{2})(?:[EAF])?', label, re.I) for label in labels]
    if all(calendar):
        first_year = entry_date.year if (entry_date.month, entry_date.day) == (1, 1) else entry_date.year + 1
        if [int(match.group(1)) for match in calendar] != list(range(first_year, first_year + count)):
            raise ValueError('LBO预测年份须连续并覆盖持有期间；非年初进入时年度标签指完整年度结束年份')
    else:
        generic = [re.fullmatch(r'(?:Y|Year\s*|第)?(\d+)(?:年)?', label, re.I) for label in labels]
        if not all(generic) or [int(match.group(1)) for match in generic] != list(range(1, count + 1)):
            raise ValueError('LBO期间请使用连续的YYYY/FY2027E或Year1、Year2标签，不能混用或漏年')


def _calc_lbo(a):
    currency, unit = _currency_unit(a)
    try:
        entry_date = date.fromisoformat(a.get('entry_date'))
        exit_date = date.fromisoformat(a.get('exit_date'))
    except (TypeError, ValueError):
        raise ValueError('LBO 必须提供 entry_date 和 exit_date（YYYY-MM-DD）')
    holding_days = (exit_date - entry_date).days
    if holding_days <= 0: raise ValueError('exit_date 必须晚于 entry_date')
    entry_ev = _num(a, 'entry_ev', minimum=0.000001)
    entry_debt = _num(a, 'entry_debt', minimum=0)
    entry_fees = _num(a, 'entry_fees', minimum=0)
    minimum_cash = _num(a, 'minimum_cash', minimum=0)
    initial_cash = _num(a, 'initial_cash', minimum=0)
    seller_rollover = _num(a, 'seller_rollover', minimum=0)
    exit_fees = _num(a, 'exit_fees', minimum=0)
    base_exit_multiple = _num(a, 'exit_multiple', minimum=0, maximum=100)
    forecasts = _forecasts(a, methods={'ebitda'})
    _lbo_horizon(entry_date, exit_date, forecasts)
    if initial_cash < minimum_cash:
        raise ValueError('初始现金不能低于最低现金；请明确资金来源和最低现金要求')
    if any(row['interest_rate'] is None for row in forecasts):
        raise ValueError('请明确每年利率，或提供全期统一 interest_rate')
    sponsor_equity = entry_ev + entry_fees + initial_cash - entry_debt - seller_rollover
    if sponsor_equity <= 0:
        raise ValueError('进入股权投入必须为正；请核对EV、债务、费用、初始现金和rollover')
    base = _simulate_lbo({**a, 'entry_ev': entry_ev, 'entry_debt': entry_debt,
                          'entry_fees': entry_fees, 'minimum_cash': minimum_cash,
                          'initial_cash': initial_cash, 'seller_rollover': seller_rollover,
                          'exit_fees': exit_fees}, forecasts, base_exit_multiple)
    shocks = [-0.2, -0.1, 0, 0.1, 0.2]
    multiples = sorted({max(0.0, base_exit_multiple + delta) for delta in (-2, -1, 0, 1, 2)})
    sensitivity = [[_simulate_lbo({**a, 'entry_ev': entry_ev, 'entry_debt': entry_debt,
                                   'entry_fees': entry_fees, 'minimum_cash': minimum_cash,
                                   'initial_cash': initial_cash, 'seller_rollover': seller_rollover,
                                   'exit_fees': exit_fees}, forecasts, mult, 1 + shock)['irr']
                    for mult in multiples] for shock in shocks]
    warnings = ['仅计算单次进入投入与单次退出，不含期间分红、分层债务、循环利息或ESOP/IPO稀释。敏感性按EBITDA/D&A同比缩放，CapEx与营运资本保持基准。',
                '进入EV按现金自由/债务自由口径；initial_cash为交易出资支持的期初现金，entry_debt为交易完成后的融资余额，不单列既有债务清偿或再融资桥。',
                'Sponsor与卖方滚存按期初股权出资比例分享全部退出股权，假设同权普通股；出资基础包括费用与期初现金，不含优先权或分配瀑布。',
                '每个预测行对应完整年度；非年初进入的年度标签指该完整年度结束年份，IRR按实际进入/退出日期计算。']
    if base['funding_gap_total'] > 0:
        warnings.append('预测期间存在未融资现金缺口；结果不是可执行的融资方案。')
    if base['exit_equity_raw'] < 0:
        warnings.append('退出股权价值为负，股权回收按零计，MOIC=0。')
    return {'method': 'lbo', 'method_label': METHODS['lbo'], 'currency': currency, 'unit': unit,
            **base, 'entry_date': entry_date.isoformat(), 'exit_date': exit_date.isoformat(),
            'holding_days': holding_days, 'entry_ev': entry_ev, 'entry_debt': entry_debt,
            'entry_fees': entry_fees, 'minimum_cash': minimum_cash,
            'initial_cash': initial_cash,
            'seller_rollover': seller_rollover, 'exit_multiple': base_exit_multiple,
            'exit_fees': exit_fees, 'sensitivity': {'rows': shocks, 'columns': multiples, 'values': sensitivity},
            'formula': 'Sponsor出资=进入EV+费用+期初现金−融资债务−卖方滚存；保留最低现金后覆盖强制偿债，再按cash sweep偿还债务；总退出股权=退出EV−债务+现金−费用；Sponsor回收=总退出股权×Sponsor出资/(Sponsor出资+卖方滚存)。',
            'warning': ' '.join(warnings)}


def calculate_valuation(method, assumptions):
    """Run a deterministic valuation method; all arithmetic stays in code."""
    a = _obj(assumptions, '模型假设')
    if not isinstance(method,str) or method not in ASSUMPTION_SCHEMAS: raise ValueError('不支持的估值方法')
    missing = missing_assumptions(method, a)
    if missing: raise ValueError('尚缺少明确假设：' + '、'.join(missing))
    allowed = set(ASSUMPTION_SCHEMAS[method]['required']) | set(ASSUMPTION_SCHEMAS[method]['optional']) | {'as_of_date','source_notes','assumption_sources','scenario','notes'}
    unknown = sorted(set(a) - allowed)
    if unknown: raise ValueError('以下假设字段未映射，未用于计算：' + '、'.join(unknown))
    if method == 'net_income':
        return _finite_result(_calc_net_income(a))
    if method == 'ps':
        return _finite_result(_calc_ps(a))
    if method == 'dcf':
        allowed_rows = {'year','ebit','revenue','ebit_margin','da','capex','delta_nwc','tax_rate'}
        unknown_rows = sorted({key for row in a['forecasts'] for key in row} - allowed_rows)
        if unknown_rows: raise ValueError('DCF预测含未映射字段：' + '、'.join(unknown_rows))
        return _finite_result(_calc_dcf(a))
    if method == 'lbo':
        allowed_rows = {'year','ebitda','da','capex','delta_nwc','tax_rate','interest_rate','mandatory_amortization','cash_sweep_pct'}
        unknown_rows = sorted({key for row in a['forecasts'] for key in row} - allowed_rows)
        if unknown_rows: raise ValueError('LBO预测含未映射字段：' + '、'.join(unknown_rows))
        return _finite_result(_calc_lbo(a))
    raise ValueError('不支持的估值方法')


def _finite_result(result):
    try:
        json.dumps(result,allow_nan=False)
    except (ValueError,OverflowError) as exc:
        raise ValueError('模型计算超出有限数值范围；请核对金额单位与假设尺度') from exc
    return result


ASSUMPTION_SCHEMAS = {
    'net_income': {'required': ['currency', 'unit', 'period', 'net_income', 'pe_multiple'], 'optional': ['diluted_shares', 'as_of_date', 'source_notes']},
    'ps': {'required': ['currency', 'unit', 'period', 'revenue', 'ps_multiple'], 'optional': ['net_debt', 'diluted_shares', 'as_of_date', 'source_notes']},
    'dcf': {'required': ['currency', 'unit', 'valuation_date', 'wacc', 'discount_timing', 'terminal_method', 'net_debt', 'minority_interest', 'forecasts'], 'optional': ['tax_rate', 'terminal_growth', 'terminal_multiple', 'as_of_date', 'source_notes']},
    'lbo': {'required': ['currency', 'unit', 'entry_date', 'exit_date', 'entry_ev', 'entry_debt', 'entry_fees', 'minimum_cash', 'initial_cash', 'seller_rollover', 'exit_fees', 'exit_multiple', 'forecasts'], 'optional': ['tax_rate', 'interest_rate', 'mandatory_amortization', 'cash_sweep_pct', 'as_of_date', 'source_notes']},
}

def parse_assumption_json(text):
    if not isinstance(text, str) or len(text) > 200_000:
        raise ValueError('模型假设解析输出格式或长度不正确')
    candidate = re.sub(r'^\s*\x60{3}(?:json)?\s*|\s*\x60{3}\s*$', '', text.strip(), flags=re.I)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find('{')
        if start < 0: raise ValueError('模型没有返回JSON假设；请调整描述后重试')
        try: value, _ = json.JSONDecoder().raw_decode(candidate[start:])
        except json.JSONDecodeError as exc: raise ValueError('模型返回的假设JSON无法解析；未运行测算') from exc
    if not isinstance(value, dict): raise ValueError('模型假设必须返回JSON对象')
    return value

def missing_assumptions(method, assumptions):
    if not isinstance(method,str) or method not in ASSUMPTION_SCHEMAS or not isinstance(assumptions, dict):
        raise ValueError('估值方法或假设结构不正确')
    schema = ASSUMPTION_SCHEMAS[method]
    missing = [key for key in schema['required'] if assumptions.get(key) is None or assumptions.get(key) == '']
    if method == 'dcf':
        terminal = assumptions.get('terminal_method')
        required_terminal = 'terminal_growth' if terminal == 'perpetuity' else 'terminal_multiple' if terminal == 'exit_multiple' else None
        if required_terminal and assumptions.get(required_terminal) is None: missing.append(required_terminal)
        forecasts = assumptions.get('forecasts')
        if isinstance(forecasts, list):
            for index, row in enumerate(forecasts, 1):
                if not isinstance(row, dict): missing.append(f'forecasts[{index}]'); continue
                for key in ('year', 'da', 'capex', 'delta_nwc'):
                    if row.get(key) is None: missing.append(f'forecasts[{index}].{key}')
                if row.get('ebit') is None and (row.get('revenue') is None or row.get('ebit_margin') is None): missing.append(f'forecasts[{index}].ebit 或 revenue + ebit_margin')
                if row.get('tax_rate') is None and assumptions.get('tax_rate') is None: missing.append(f'forecasts[{index}].tax_rate')
    if method == 'lbo':
        forecasts = assumptions.get('forecasts')
        if isinstance(forecasts, list):
            for index, row in enumerate(forecasts, 1):
                if not isinstance(row, dict): missing.append(f'forecasts[{index}]'); continue
                for key in ('year', 'ebitda', 'da', 'capex', 'delta_nwc'):
                    if row.get(key) is None: missing.append(f'forecasts[{index}].{key}')
                for key in ('tax_rate', 'interest_rate', 'mandatory_amortization', 'cash_sweep_pct'):
                    if row.get(key) is None and assumptions.get(key) is None: missing.append(f'forecasts[{index}].{key}')
    return list(dict.fromkeys(missing))

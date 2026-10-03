import unittest
from workos.valuation import calculate_valuation


def lbo_fixture(**overrides):
    base={'currency':'RMB','unit':'millions','entry_date':'2026-01-01','exit_date':'2026-12-31',
          'entry_ev':1000,'entry_debt':500,'entry_fees':10,'minimum_cash':10,'initial_cash':10,
          'seller_rollover':0,'exit_fees':10,'exit_multiple':10,'tax_rate':.25,'interest_rate':.06,
          'mandatory_amortization':20,'cash_sweep_pct':.5,
          'forecasts':[{'year':'2026','ebitda':100,'da':10,'capex':20,'delta_nwc':5}]}
    return {**base,**overrides}


class ValuationFrameworkTests(unittest.TestCase):
    def test_net_income_pe_produces_equity_value_and_per_share(self):
        r = calculate_valuation('net_income', {'currency':'RMB','unit':'百万元','period':'FY2025A','net_income':100,'pe_multiple':12,'diluted_shares':50})
        self.assertEqual(r['equity_value'], 1200)
        self.assertEqual(r['implied_value_per_share'], 24)

    def test_ps_uses_equity_value_per_sales_and_bridges_to_ev(self):
        r = calculate_valuation('ps', {'currency':'RMB','unit':'百万元','period':'FY2025A','revenue':500,'ps_multiple':2,'net_debt':75})
        self.assertEqual(r['equity_value'], 1000)
        self.assertEqual(r['implied_enterprise_value'], 1075)
        self.assertIn('P/S', r['formula'])

    def test_dcf_fcff_timing_terminal_and_equity_bridge(self):
        a={'currency':'RMB','unit':'百万元','valuation_date':'2025-12-31','wacc':0.10,'discount_timing':'year_end','terminal_method':'perpetuity','terminal_growth':0.02,'net_debt':100,'minority_interest':10,'forecasts':[
            {'year':'2026E','ebit':100,'da':10,'capex':20,'delta_nwc':5,'tax_rate':0.25},
            {'year':'2027E','ebit':120,'da':12,'capex':25,'delta_nwc':6,'tax_rate':0.25},
        ]}
        r=calculate_valuation('dcf',a)
        self.assertAlmostEqual(r['forecast'][0]['fcff'],60)
        self.assertAlmostEqual(r['enterprise_value'],sum(x['pv_fcff'] for x in r['forecast'])+r['pv_terminal_value'])
        self.assertAlmostEqual(r['equity_value'],r['enterprise_value']-110)
        self.assertEqual(r['valuation_date'],'2025-12-31')

    def test_dcf_rejects_invalid_terminal_growth_and_omitted_bridge(self):
        base={'currency':'RMB','unit':'百万元','valuation_date':'2025-12-31','wacc':0.08,'discount_timing':'year_end','terminal_method':'perpetuity','terminal_growth':0.08,'net_debt':0,'minority_interest':0,'forecasts':[{'year':'2026E','ebit':100,'da':10,'capex':5,'delta_nwc':0,'tax_rate':0.25}]}
        with self.assertRaisesRegex(ValueError,'WACC'):
            calculate_valuation('dcf',base)
        missing={**base,'terminal_growth':0.02};missing.pop('net_debt')
        with self.assertRaisesRegex(ValueError,'net_debt'):
            calculate_valuation('dcf',missing)

    def test_lbo_rolls_debt_and_cash_and_uses_dated_irr(self):
        a={'currency':'RMB','unit':'百万元','entry_date':'2026-01-01','exit_date':'2029-12-31','entry_ev':1000,'entry_debt':500,'entry_fees':10,'minimum_cash':10,'initial_cash':10,'seller_rollover':0,'exit_fees':10,'exit_multiple':10,'forecasts':[
            {'year':str(y),'ebitda':e,'da':10,'capex':20,'delta_nwc':5,'tax_rate':0.25,'interest_rate':0.06,'mandatory_amortization':20,'cash_sweep_pct':0.5}
            for y,e in [(2026,100),(2027,120),(2028,140),(2029,160)]
        ]}
        r=calculate_valuation('lbo',a)
        self.assertEqual(r['entry_sponsor_equity'],520)
        self.assertLess(r['exit_debt'],r['entry_debt'])
        self.assertGreater(r['exit_cash'],0)
        self.assertAlmostEqual(r['irr'],r['moic']**(365/1460)-1)
        self.assertEqual(len(r['sensitivity']['values']),5)

    def test_negative_net_income_and_unknown_method_are_not_faked(self):
        with self.assertRaisesRegex(ValueError,'P/E'):
            calculate_valuation('net_income',{'currency':'RMB','unit':'百万元','period':'FY2025A','net_income':-1,'pe_multiple':10})
        with self.assertRaisesRegex(ValueError,'不支持'):
            calculate_valuation('magic',{})
        with self.assertRaisesRegex(ValueError,'不支持'):
            calculate_valuation([], {})
        with self.assertRaisesRegex(ValueError,'有限数值'):
            calculate_valuation('net_income',{'currency':'RMB','unit':'millions','period':'FY2026E','net_income':1e308,'pe_multiple':12})

    def test_lbo_rollover_allocates_exit_equity_without_inflating_returns(self):
        sole = calculate_valuation('lbo',lbo_fixture())
        shared = calculate_valuation('lbo',lbo_fixture(seller_rollover=100))
        self.assertEqual(shared['entry_sponsor_equity'],420)
        self.assertEqual(shared['total_entry_equity'],520)
        self.assertAlmostEqual(shared['sponsor_ownership'],420/520)
        self.assertAlmostEqual(shared['seller_ownership'],100/520)
        self.assertAlmostEqual(shared['sponsor_proceeds']+shared['seller_proceeds'],shared['total_exit_proceeds'])
        self.assertAlmostEqual(shared['sponsor_proceeds'],shared['total_exit_proceeds']*420/520)
        self.assertLess(shared['sponsor_proceeds'],sole['sponsor_proceeds'])
        self.assertAlmostEqual(shared['moic'],sole['moic'])
        self.assertAlmostEqual(shared['irr'],sole['irr'])
        self.assertIn('同权普通股',shared['warning'])

    def test_lbo_actual_closing_cash_is_funded_and_minimum_cash_is_reserved(self):
        a=lbo_fixture(initial_cash=30,seller_rollover=100,cash_sweep_pct=1)
        result=calculate_valuation('lbo',a)
        self.assertEqual(result['entry_sponsor_equity'],440)
        self.assertEqual(result['total_entry_equity'],540)
        row=result['rows'][0]
        available=a['initial_cash']+row['cash_before_debt']
        self.assertLessEqual(row['mandatory_paid']+row['cash_sweep'],max(0,available-a['minimum_cash']))
        self.assertAlmostEqual(row['ending_debt'],a['entry_debt']-row['mandatory_paid']-row['cash_sweep'])
        self.assertAlmostEqual(row['ending_cash'],a['minimum_cash'])
        self.assertEqual(row['funding_gap'],0)
        with self.assertRaisesRegex(ValueError,'初始现金'):
            calculate_valuation('lbo',lbo_fixture(initial_cash=5))

    def test_lbo_unfunded_floor_and_mandatory_shortfall_are_explicit(self):
        a=lbo_fixture(forecasts=[{'year':'2026','ebitda':10,'da':1,'capex':20,'delta_nwc':5}],
                      interest_rate=0,tax_rate=0,mandatory_amortization=20,cash_sweep_pct=1)
        result=calculate_valuation('lbo',a)
        row=result['rows'][0]
        self.assertEqual(row['mandatory_paid'],0)
        self.assertEqual(row['cash_sweep'],0)
        self.assertEqual(row['mandatory_shortfall'],20)
        self.assertEqual(row['cash_floor_shortfall'],15)
        self.assertEqual(row['funding_gap'],35)
        self.assertEqual(result['funding_gap_total'],35)
        self.assertIn('未融资现金缺口',result['warning'])

    def test_lbo_requires_complete_annual_horizon_and_preserves_actual_dates(self):
        with self.assertRaisesRegex(ValueError,'年度数量'):
            calculate_valuation('lbo',lbo_fixture(exit_date='2029-12-31'))
        with self.assertRaisesRegex(ValueError,'年度数量'):
            calculate_valuation('lbo',lbo_fixture(entry_date='2026-03-15',exit_date='2026-12-31'))
        with self.assertRaisesRegex(ValueError,'连续'):
            calculate_valuation('lbo',lbo_fixture(forecasts=[{'year':'2027','ebitda':100,'da':10,'capex':20,'delta_nwc':5}]))
        rolling=lbo_fixture(entry_date='2026-03-15',exit_date='2027-03-15',
                            forecasts=[{'year':'Year1','ebitda':100,'da':10,'capex':20,'delta_nwc':5}])
        result=calculate_valuation('lbo',rolling)
        self.assertEqual(result['holding_days'],365)
        self.assertAlmostEqual(result['irr'],result['moic']-1)
        same=calculate_valuation('lbo',{**rolling,'forecasts':[{**rolling['forecasts'][0],'year':'FY2027E'}]})
        self.assertEqual(same['irr'],result['irr'])

    def test_lbo_zero_exit_allocations_still_conserve_cash(self):
        result=calculate_valuation('lbo',lbo_fixture(seller_rollover=100,exit_multiple=0))
        self.assertEqual(result['total_exit_proceeds'],0)
        self.assertEqual(result['sponsor_proceeds'],0)
        self.assertEqual(result['seller_proceeds'],0)
        self.assertEqual(result['moic'],0)
        self.assertEqual(result['irr'],-1)


if __name__=='__main__':unittest.main()

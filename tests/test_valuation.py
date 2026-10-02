import unittest
from workos.valuation import calculate_valuation


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


if __name__=='__main__':unittest.main()

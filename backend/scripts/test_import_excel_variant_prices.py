import unittest
from copy import deepcopy

from import_excel_variant_prices import identity, make_plan


def model(code='PJ1183-5055', price=None, **overrides):
    return {'id':1, 'code':code, 'catalog_scope':'standard', 'factory_code':None,
            'general':{'model_no':'PJ1183','variant_no':'V-5055'},
            'selling_price':price, 'selling_price_currency':'USD' if price else None,
            'selling_price_source':'catalog' if price else None,
            'selling_price_request_id':None, 'selling_price_updated_at':None, **overrides}


def plan(rows, models=None):
    return make_plan({'name':'source.xlsx','sha256':'test', 'rows':[
        {'row':i+2,'code':code,'amount':price} for i,(code,price) in enumerate(rows)]},
        {'revision':'test','models':models if models is not None else [model()]})


class ImportPricesTests(unittest.TestCase):
    def test_decimal_uses_excel_not_current_price(self):
        result=plan([('PJ-1183-V5055','4,50')],[model(price='20.0000')])
        self.assertEqual(result['changes'][0]['target'],'4.80')
        self.assertEqual(result['changes'][0]['before']['selling_price'],'20.0000')

    def test_blank_prices_are_preserved_and_zero_is_valid(self):
        self.assertEqual(plan([('PJ-1183-V5055',None)])['changes'],[])
        self.assertEqual(plan([('PJ-1183-V5055','0,00')])['changes'][0]['target'],'0.30')

    def test_idempotency(self):
        result=plan([('PJ-1183-V5055','4,50')],[model(price='4.8000')])
        self.assertEqual(result['changes'],[])
        self.assertEqual(len(result['unchanged']),1)

    def test_conflicting_duplicates_never_choose_price(self):
        result=plan([('PJ-1183-V5055','4,50'),('pj1183-v-5055','4,60')])
        self.assertEqual(result['changes'],[])
        self.assertEqual(len(result['conflicts']),1)

    def test_identical_duplicate_source_updates_once(self):
        result=plan([('PJ-1183-V5055','4,50'),('pj1183-v-5055','4,50')])
        self.assertEqual(len(result['changes']),1)
        self.assertEqual(result['changes'][0]['source_rows'],[2,3])

    def test_different_model_and_usluga_are_not_matches(self):
        self.assertEqual(plan([('PJ-9999-V5055','4,50')])['changes'],[])
        self.assertEqual(plan([('PJ-1183-V5055','4,50')],[model(catalog_scope='usluga')])['changes'],[])

    def test_format_normalization_without_fuzzy_matching(self):
        self.assertEqual(identity('РJ-1183-v5055'),('PJ1183','5055'))
        self.assertEqual(identity('FJ-6019-5984'),('FJ6019','5984'))
        self.assertIsNone(identity('PJ-1183'))
        self.assertEqual(identity('PJ-1183-V0002'),('PJ1183','0002'))

    def test_currency_mismatch_aborts_and_snapshot_unmodified(self):
        models=[model(selling_price_currency='UZS')]
        saved=deepcopy(models)
        with self.assertRaises(ValueError):
            plan([('PJ-1183-V5055','4,50')],models)
        self.assertEqual(models,saved)

    def test_legacy_exact_code_never_spreads_to_variants(self):
        source={'name':'source.xlsx','sha256':'test','rows':[{'row':2,'code':'Р-10577','amount':'5,80'}]}
        snapshot={'revision':'test','models':[model(code='P10577',general={'model_no':'P10577'}),
                   model(code='P10577-2',id=2,general={'model_no':'P10577','variant_no':'2'})]}
        self.assertEqual(make_plan(source,snapshot)['changes'],[])
        result=make_plan(source,snapshot,include_legacy=True)
        self.assertEqual([(r['id'],r['target']) for r in result['changes']],[(1,'6.10')])


if __name__ == '__main__':
    unittest.main()

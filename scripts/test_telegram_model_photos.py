import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from plan_telegram_model_photos import build
from prepare_telegram_photos import prepare
from build_telegram_photo_bundle import build as bundle


def model(mid=1, base='XJ3062', scope='standard'):
    return {'id': mid, 'code': base+'-123', 'catalog_scope': scope,
            'general_details': {'model_no': base, 'variant_no': 'V-123'}, 'images': []}


def attachment(mid, name):
    return {'id': 'shared-mediamessage-'+str(mid), 'name': name, 'text': name}


class PhotoTests(unittest.TestCase):
    def test_single_letter_and_v_suffix_are_distinct(self):
        plan=build([attachment(1,'C1377 V-125.jpg'),attachment(2,'PJ1032V V-5759.jpg'),
                    attachment(3,'PJ1032V-5759.jpg')],
                   [model(1,'C1377'),model(2,'PJ1032V'),model(3,'PJ1032')])
        self.assertEqual({r['model_no']:r['source']['id'] for r in plan['selected']},
                         {'C1377':'shared-mediamessage-1','PJ1032V':'shared-mediamessage-2','PJ1032':'shared-mediamessage-3'})

    def test_downloaded_source_is_stable_and_jpeg_preferred(self):
        files=[attachment(1,'XJ3062.jpg'),attachment(2,'XJ3062.png')]
        self.assertEqual(build(files,[model()])['selected'][0]['source']['id'],files[0]['id'])
        frozen=[{'model_no':'XJ3062','source':files[1]}]
        self.assertEqual(build(files,[model()],frozen)['selected'][0]['source']['id'],files[1]['id'])

    def test_bundle_holds_only_actual_variants_using_model_fallback(self):
        plan={'selected':[{'model_no':'XJ3062','source':attachment(1,'XJ3062.jpg'),
                         'models':[{'id':i,'code':str(i)} for i in range(1,5)]}],
              'source_group':'Milana Fotosessiya','source_group_id':'-1002871659105',
              'indexed_files':1,'unmatched_families':[]}
        safety={'images':[], 'models':[
            {'id':1,'code':'1','general':{'variant_no':'V-1'},'independent_variant_url':None,'effective_variant_url':'old-model'},
            {'id':2,'code':'2','general':{'variant_no':''},'independent_variant_url':None,'effective_variant_url':'old-model'},
            {'id':3,'code':'3','general':{'variant_no':'V-3'},'independent_variant_url':'fabric','effective_variant_url':'fabric'},
            {'id':4,'code':'4','general':{'variant_no':'V-4'},'independent_variant_url':None,'effective_variant_url':None}]}
        photo={key:'x' for key in ('stored_name','sha256','original_sha256','pixel_sha256','content_type')}
        photo.update(model_no='XJ3062', source=plan['selected'][0]['source'], stored_bytes=1,bytes=1,width=1,height=1)
        result=bundle(plan,[photo],safety)
        self.assertEqual([r['id'] for r in result['held']],[1])
        self.assertEqual([r['id'] for r in result['photos'][0]['models']],[2,3,4])
        with self.assertRaises(AssertionError): bundle(plan,[],safety)

    def test_latest_named_photo_and_family_variants(self):
        plan = build([attachment(1,'XJ-3062 V-001.jpg'), attachment(2,'XJ3062_V-987.jpg')],
                     [model(),model(2)])
        self.assertEqual(plan['selected'][0]['source']['id'],'shared-mediamessage-2')
        self.assertEqual(len(plan['selected'][0]['models']),2)

    def test_does_not_match_partial_number_or_camera_name(self):
        plan = build([attachment(1,'XJ30621.jpg'), attachment(2,'ICE_3062.jpg'),
                      attachment(3,'hf_20260905_3062.png')], [model()])
        self.assertEqual(plan['selected'], [])

    def test_confusable_letters_and_separators(self):
        plan = build([attachment(1,'ХJ-3062_V-991.jpg')], [model()])
        self.assertEqual(plan['selected'][0]['model_no'], 'XJ3062')

    def test_protected_catalogs_and_documents_excluded(self):
        hidden = model(2); hidden['code']='LEGACY-XJ3062'
        plan = build([attachment(1,'XJ3062.pdf')], [model(), hidden, model(3,scope='usluga')])
        self.assertEqual(plan['selected'], [])
        plan = build([attachment(2,'XJ3062.jpg')], [model(), hidden, model(3,scope='usluga')])
        self.assertEqual([m['id'] for m in plan['selected'][0]['models']], [1])

    def test_prefers_single_model_image_over_family_composite(self):
        plan = build([attachment(2,'XJ3062 PM7007.jpg'),attachment(1,'XJ3062.jpg')],
                     [model(),model(2,'PM7007')])
        row = next(r for r in plan['selected'] if r['model_no']=='XJ3062')
        self.assertEqual(row['source']['id'],'shared-mediamessage-1')

    def test_source_is_unchanged_and_derivative_preserves_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'evidence/telegram-originals/original.png'
            source.parent.mkdir(parents=True)
            Image.new('RGB',(70,90),(43,80,121)).save(source)
            original=source.read_bytes()
            row={'model_no':'XJ3062','local_path':str(source.relative_to(root)),
                 'bytes':len(original),'source':attachment(12,'XJ3062.png')}
            row['source']['text']+='\n'+str(round(len(original)/1024,1))+'KB'
            result=prepare(root,row)
            self.assertEqual(source.read_bytes(),original)
            with Image.open(root/'evidence/telegram-prepared'/result['stored_name']) as prepared:
                with Image.open(source) as initial:
                    self.assertEqual(prepared.convert('RGB').tobytes(), initial.tobytes())
            self.assertEqual(prepare(root,row),result)
            json.dumps(result)
            row['source']['text']='XJ3062.png\n15.8MB'
            with self.assertRaises(AssertionError): prepare(root,row)

    def test_source_outside_task_originals_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                prepare(Path(tmp), {'local_path':'../outside.png','bytes':0})


if __name__=='__main__':
    unittest.main()

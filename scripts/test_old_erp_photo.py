import copy
import hashlib
import unittest
from validate_old_erp_photo import validate, validate_blank_target, validate_existing


class SourceGuards(unittest.TestCase):
    def photo(self):
        data = b'original bytes'
        digest = hashlib.sha256(data).hexdigest()
        return {'model_no': 'B3189', 'stored_name': 'old_erp_model_20260908_430_'+digest[:16]+'.jpg',
                'sha256': digest, 'original_sha256': digest, 'stored_bytes': len(data),
                'original_bytes': len(data), 'width': 1000, 'height': 1400,
                'source': {'id': '430', 'url': 'https://10.100.50.199:8443/uzerp/prepareSewModel.htm?id=430',
                           'model_no': 'В-3189', 'dom_model_no': 'В-3189', 'captured_at': '2026-09-08',
                           'acquisition': 'rendered_dom_data_image', 'reviewed': True,
                           'bytes': len(data), 'dom_dimensions': [1000, 1400]}}, data

    def test_exact_record_and_original_bytes_required(self):
        photo, data = self.photo()
        validate(photo, data)
        for key, value in [('url', 'https://example.com/430'), ('dom_model_no', 'B3188'),
                           ('reviewed', False), ('bytes', 1), ('dom_dimensions', [320, 320])]:
            changed = copy.deepcopy(photo)
            changed['source'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate(changed, data)
        with self.assertRaises(AssertionError):
            validate(photo, data+b'changed')

    def test_only_exact_empty_target_can_receive_fallback(self):
        validate_blank_target('B3189', {'model_no': 'В-3189'}, 'B3189', None)
        with self.assertRaises(AssertionError):
            validate_blank_target('B3189', {'model_no': 'B3189'}, 'B3189', '/user-picture.jpg')
        with self.assertRaises(AssertionError):
            validate_blank_target('B3189', {'model_no': 'B3190'}, 'B3189', None)

    def test_existing_family_source_requires_exact_file_and_printed_label(self):
        photo, data = self.photo()
        photo['stored_name'] = 'old_erp_model_' + photo['sha256'][:24] + '.jpg'
        photo['source'] = {'id': 12, 'url': 'https://erp.milanapremium.uz/models/12', 'reviewed': True,
                           'file_url': '/storage/model-files/' + photo['stored_name'], 'printed_model_no': 'B-3189'}
        validate_existing(photo, data)
        for key, value in [('file_url','/another.jpg'), ('printed_model_no','B3188'), ('id',13)]:
            changed = copy.deepcopy(photo)
            changed['source'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_existing(changed, data)


if __name__ == '__main__':
    unittest.main()

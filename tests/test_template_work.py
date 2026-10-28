import unittest
from company_x2.template_work import plan, execute
from company_x2.template_work import safe_request
from company_x2.template_work import suggest


class TemplateWorkTests(unittest.TestCase):
    def test_wide_reordered_file_and_corrupted_serialization(self):
        import csv
        import io
        from unittest.mock import patch
        source_columns=['c'+str(i) for i in range(100)]
        source_values=['00'+str(i) for i in range(100)]
        source_values[7]='日本語, quoted'
        buffer=io.StringIO(newline='')
        writer=csv.writer(buffer);writer.writerow(source_columns);writer.writerow(source_values)
        text=buffer.getvalue();columns=list(reversed(source_columns))
        mapping={column:column for column in columns}
        proposal=plan(text,columns,mapping)
        result=execute(text,columns,mapping,[],proposal['plan_sha256'],True)
        self.assertEqual(list(csv.reader(io.StringIO(result['csv'])))[1],list(reversed(source_values)))
        real_writer=csv.writer
        class CorruptWriter:
            def __init__(self,*args,**kwargs):self.writer=real_writer(*args,**kwargs)
            def writerow(self,row):return self.writer.writerow(row)
            def writerows(self,rows):
                for row in rows:
                    changed=list(row);changed[0]='silently changed'
                    self.writer.writerow(changed)
        with patch('company_x2.template_work.csv.writer',CorruptWriter):
            with self.assertRaisesRegex(ValueError,'Source preservation'):
                execute(text,columns,mapping,[],proposal['plan_sha256'],True)

    def test_bilingual_mapping_and_ambiguous_source(self):
        data = {'purpose': 'Prepare product template', 'csv': 'sku,title\n001,Test\n',
                'template_csv': '商品コード,商品名,価格\n',
                'risk_context': dict(sensitive_data='no', critical_use='no', extra_liability='no')}
        result = suggest(data)
        self.assertEqual(result['mapping'], {'商品コード': 'sku', '商品名': 'title'})
        self.assertEqual(result['plan']['questions'][0]['column'], '価格')
        data.update(csv='sku,品番,title\n001,002,Test\n')
        result = suggest(data)
        self.assertNotIn('商品コード', result['mapping'])

    def test_safe_workflow_and_changed_purpose(self):
        data = {'purpose': 'Prepare product file', 'csv': 'sku\n001\n',
                'columns': ['SKU'], 'mapping': {'SKU': 'sku'},
                'risk_context': dict(sensitive_data='no', critical_use='no', extra_liability='no')}
        p = safe_request(data)
        data.update(accepted=True, approval_sha256=p['approval_sha256'])
        self.assertTrue(safe_request(data, True)['report']['verified'])
        data['purpose'] = 'Another purpose'
        with self.assertRaises(ValueError):
            safe_request(data, True)

    def test_sensitive_input_and_destination_rejected(self):
        data = {'purpose': 'Prepare file', 'csv': 'sku\n001\n', 'columns': ['email'],
                'mapping': {'email': 'sku'},
                'risk_context': dict(sensitive_data='no', critical_use='no', extra_liability='no')}
        with self.assertRaises(ValueError):
            safe_request(data)
        data.update(columns=['SKU'], mapping={'SKU': 'sku'}, csv='sku\n=IMPORTXML()\n')
        with self.assertRaises(ValueError):
            safe_request(data)

    def test_unknown_scope_rejected(self):
        with self.assertRaises(ValueError):
            safe_request({'purpose': 'Prepare file'})

    def test_exact_values_and_order(self):
        text = 'sku,title\n001,"日本語, item"\n002,English\n'
        columns, mapping = ['Title', 'SKU'], {'Title': 'title', 'SKU': 'sku'}
        proposal = plan(text, columns, mapping)
        result = execute(text, columns, mapping, [], proposal['plan_sha256'], True)
        self.assertIn('001', result['csv'])
        self.assertIn('日本語, item', result['csv'])
        self.assertTrue(result['report']['verified'])

    def test_changed_data_requires_new_consent(self):
        p = plan('sku\n001\n', ['SKU'], {'SKU': 'sku'})
        with self.assertRaises(ValueError):
            execute('sku\n002\n', ['SKU'], {'SKU': 'sku'}, [], p['plan_sha256'], True)

    def test_no_inference_and_no_silent_mapping(self):
        p = plan('sku\n001\n', ['SKU', 'Price'], {'SKU': 'sku'})
        self.assertEqual(p['questions'][0]['column'], 'Price')
        with self.assertRaises(ValueError):
            execute('sku\n001\n', ['SKU', 'Price'], {'SKU': 'sku'}, [], p['plan_sha256'], True)

    def test_missing_required_is_reported(self):
        text = 'sku,title\n001,\n'
        columns, mapping = ['SKU', 'Title'], {'SKU': 'sku', 'Title': 'title'}
        p = plan(text, columns, mapping, ['Title'])
        result = execute(text, columns, mapping, ['Title'], p['plan_sha256'], True)
        self.assertFalse(result['report']['ready_for_import'])
        self.assertEqual(result['report']['issues'][0]['reason'], 'missing_required')

    def test_ambiguous_template_rejected(self):
        with self.assertRaises(ValueError):
            plan('sku\n001\n', ['SKU', 'SKU'], {'SKU': 'sku'})

    def test_explicit_consent_required(self):
        p = plan('sku\n001\n', ['SKU'], {'SKU': 'sku'})
        with self.assertRaises(ValueError):
            execute('sku\n001\n', ['SKU'], {'SKU': 'sku'}, [], p['plan_sha256'])

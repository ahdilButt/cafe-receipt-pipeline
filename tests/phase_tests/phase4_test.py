import os
from pathlib import Path

# Load .env
for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

import anthropic
from src.database import get_connection, init_db, seed_db
from src.pipeline import load_image_as_base64
from src.pass1_recon import run_pass1
from src.pass2_extract import run_pass2

conn = get_connection()
init_db(conn)
seed_db(conn)

cursor = conn.execute('SELECT * FROM suppliers')
cols = [d[0] for d in cursor.description]
suppliers = [dict(zip(cols, row)) for row in cursor.fetchall()]

client = anthropic.Anthropic()
image_b64 = load_image_as_base64(Path('data/receipts/R001.jpg'))

print('=== PASS 1: RECON ===')
p1 = run_pass1(client, image_b64, suppliers)
print(f'Supplier: {p1.supplier_name}')
print(f'Confidence: {p1.supplier_match_confidence}')
print(f'Invoice: {p1.invoice_number}')
print(f'Date: {p1.date}')
print(f'Currency: {p1.currency}')
print(f'Format: {p1.format_type}')
print(f'Quality: {p1.image_quality}')
print(f'Observations: {p1.observations}')

print()
print('=== PASS 2: EXTRACT ===')
supplier = next((s for s in suppliers if s['name'] == p1.supplier_name), None)
p2 = run_pass2(client, image_b64, supplier or {}, p1)
print(f'Line items: {len(p2.line_items)}')
for item in p2.line_items:
    print(f'  {item.item_index}. {item.raw_description}: qty={item.quantity}, unit={item.raw_unit}, '
          f'price={item.unit_price}, total={item.line_total}, pack_size={item.pack_size}')
print(f'Receipt total: {p2.receipt_total}')
print(f'Calculated sum: {p2.calculated_sum}')
print(f'Sum matches: {p2.sum_matches_total}')

conn.close()

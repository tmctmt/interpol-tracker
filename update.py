import csv
import os
import sys
from pathlib import Path
from random import random
from string import ascii_lowercase

import curl_cffi
from tenacity import retry, stop_after_attempt, wait_exponential

FIELDS = ['entity_id', 'forename', 'name', 'date_of_birth', 'nationalities']
BASE_URL = 'https://ws-public.interpol.int/notices/v1'
OUT = Path(os.getenv('OUT', 'red_notices.csv'))
MSG = Path(os.getenv('MSG', 'msg.txt'))

class InterpolClient:
    def __init__(self):
        self.session = curl_cffi.Session(impersonate='chrome')

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    def search(self, **query):
        query.setdefault('random', random())
        resp = self.session.get(f'{BASE_URL}/red', params=query)
        resp.raise_for_status()
        data = resp.json()
        return data['_embedded']['notices'], data['total']

def get_notices():
    client = InterpolClient()
    chars = [*ascii_lowercase, '[^' + ascii_lowercase + ']']
    queue = chars.copy()
    notices = {}
    while queue:
        prefix = queue.pop()
        chunk, total = client.search(name='^' + prefix, resultPerPage=160)
        notices.update({n['entity_id']: n for n in chunk})
        if len(chunk) < total:
            queue.extend(prefix + c for c in chars)
    notices = sorted(notices.values(), key=sort_key)
    return notices

def sort_key(notice):
    return [int(s) for s in notice['entity_id'].split('/')]

def name(notice):
    return ' '.join([
        notice['forename'] or '',
        notice['name'] or ''
    ]).strip() + f' (#{notice['entity_id']})'

if __name__ == '__main__':
    notices = get_notices()
    
    for notice in notices:
        for key, value in list(notice.items()):
            if key not in FIELDS:
                del notice[key]
                continue
            if value is None:
                value = ''
            if isinstance(value, list):
                value = ','.join(value)
            notice[key] = str(value)

    if OUT.exists():
        with open(OUT, encoding='utf-8') as file:
            old_map = {n['entity_id']: n for n in csv.DictReader(file)}
            new_map = {n['entity_id']: n for n in notices}

        if old_map == new_map:
            sys.exit()

        with open(MSG, 'w') as file:
            for entity_id in {*new_map.keys(), *old_map.keys()}:
                old = old_map.get(entity_id)
                new = new_map.get(entity_id)
                if new and not old:
                    file.write(f'added {name(new)}\n')
                elif not new and old:
                    file.write(f'removed {name(old)}\n')
                elif old != new:
                    file.write(f'changed {name(new)}\n')

    with open(OUT, 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(notices)
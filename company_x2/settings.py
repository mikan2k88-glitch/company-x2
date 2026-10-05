import os
from .store import Store
from .supabase_store import SupabaseStore


def build_store(environ=None, *, local_path='work/company-x2.db'):
    env = os.environ if environ is None else environ
    backend = env.get('STORAGE_BACKEND', 'supabase' if env.get('RENDER') else 'sqlite')
    if backend == 'sqlite':
        if env.get('RENDER'):
            raise ValueError('Render trial requires Supabase; ephemeral SQLite is disabled')
        return Store(local_path)
    if backend != 'supabase':
        raise ValueError('Unknown STORAGE_BACKEND')
    url = env.get('SUPABASE_URL', '')
    key = env.get('SUPABASE_SECRET_KEY') or env.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if not url or not key:
        raise ValueError('SUPABASE_URL and SUPABASE_SECRET_KEY are required')
    return SupabaseStore(url, key)

SCHEMA='''create table if not exists outreach_contacts(id text primary key,url text unique not null,issue_id text not null,author text not null,message text not null,status text not null default 'draft',comment_url text,attempted_at text,reply_id integer,reply_text text,next_message text,created_at text not null default CURRENT_TIMESTAMP);'''
def rpc(store,action,p):
    with store.connect() as db:
        db.execute('begin immediate')
        if action=='ping':return {'outreach_schema_version':25}
        if action=='prepare':
            db.execute('insert or ignore into outreach_contacts(id,url,issue_id,author,message) values(?,?,?,?,?)',tuple(p[k] for k in ('id','url','issue_id','author','message')));return True
        if action=='list':return [dict(r) for r in db.execute('select * from outreach_contacts order by created_at desc limit 50')]
        if action=='observe':
            return bool(db.execute("update outreach_contacts set reply_id=?,reply_text=?,next_message=? where id=? and status='sent' and coalesce(reply_id,0)<?",(p['reply_id'],p['reply_text'][:2000],p['next_message'][:2000],p['id'],p['reply_id'])).rowcount)
        if action=='claim':
            if db.execute("select 1 from outreach_contacts where attempted_at>=date('now')").fetchone():return None
            r=db.execute("select * from outreach_contacts where status='draft' order by created_at,id limit 1").fetchone()
            if not r:return None
            db.execute("update outreach_contacts set status='sending',attempted_at=CURRENT_TIMESTAMP where id=?",(r['id'],));return dict(r)
        if action in ('finish','uncertain'):
            state='sent' if action=='finish' else 'uncertain'
            return bool(db.execute("update outreach_contacts set status=?,comment_url=? where id=? and status='sending'",(state,p.get('comment_url'),p['id'])).rowcount)
        raise ValueError('Unknown outreach action')

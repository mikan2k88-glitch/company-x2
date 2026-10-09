"""SQLite implementation of the isolated support RPC."""
SCHEMA='''create table if not exists support_tickets (
 id text primary key, token_hash text not null, request_key text not null,
 fingerprint text not null, kind text not null, message text not null, guidance text not null,
 reply text not null default '', status text not null default 'open',
 created_at text not null default CURRENT_TIMESTAMP, updated_at text not null default CURRENT_TIMESTAMP,
 unique(token_hash,request_key));'''

def visible(row):
    if not row:return None
    return {k:row[k] for k in ('id','kind','message','guidance','reply','status','created_at','updated_at')}

def create_in(db,p):
    old=db.execute('select * from support_tickets where token_hash=? and request_key=?',(p['token_hash'],p['request_key'])).fetchone()
    if old:
        if old['fingerprint']!=p['fingerprint']:raise ValueError('受付キーを同じ内容で再試行してください')
        return {'id':old['id']}
    counts=db.execute("select count(*) total,sum(token_hash=?) own from support_tickets where created_at>=date('now')",(p['token_hash'],)).fetchone()
    if counts['total']>=100 or (counts['own'] or 0)>=3:raise ValueError('本日の受付上限です。日本時間9時以降に再試行してください')
    db.execute('insert into support_tickets(id,token_hash,request_key,fingerprint,kind,message,guidance) values(?,?,?,?,?,?,?)',tuple(p[k] for k in ('id','token_hash','request_key','fingerprint','kind','message','guidance')))
    return {'id':p['id']}

def rpc(store,action,p):
    with store.connect() as db:
        db.execute('begin immediate')
        if action=='ping':return {'support_schema_version':21}
        if action=='create':
            return create_in(db,p)
        if action=='get':return visible(db.execute('select * from support_tickets where id=? and token_hash=?',(p['id'],p['token_hash'])).fetchone())
        if action=='list':return [visible(r) for r in db.execute("select * from support_tickets order by (status='open') desc,created_at desc,id desc limit 50")]
        if action=='reply':
            changed=db.execute("update support_tickets set reply=?,status='answered',updated_at=CURRENT_TIMESTAMP where id=?",(p['reply'],p['id'])).rowcount
            if not changed:raise ValueError('問い合わせがありません')
            return {'answered':True}
        raise ValueError('Unknown support operation')

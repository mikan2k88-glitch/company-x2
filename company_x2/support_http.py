from . import support

def get_route(handler,path,store):
    if path=='/api/support/config':
        handler.respond(200,{'ready':support.ready(store),'operator_mode':'individual',
            'notice':'本番販売は準備中です。問い合わせの受付だけでは販売者情報の開示は完了しません。'})
    elif path.startswith('/api/support/tickets/'):
        ticket=support.get(store,path.rsplit('/',1)[-1],handler.headers.get('X-Support-Token',''))
        handler.respond(200 if ticket else 404,ticket or {'error':'問い合わせがありません'})
    elif path=='/api/company/support':
        cases=store.case_rpc('list')
        mapped={c['ticket_id']:{**c['ticket'],'case':{k:v for k,v in c.items() if k!='ticket'}} for c in cases}
        for t in store.support_rpc('list'):
            if t['id'] not in mapped:mapped[t['id']]=t
        handler.respond(200,{'items':list(mapped.values())})
    else:return False
    return True

def post_route(handler,path,data,store):
    if path=='/api/support/tickets':handler.respond(202,support.create(store,data,handler.headers.get('X-Support-Token',''),handler.headers.get('X-Order-Token','')))
    elif path=='/api/company/support/reply':handler.respond(200,support.reply(store,data))
    elif path=='/api/company/support/resolve':handler.respond(200,support.resolve(store,data))
    else:return False
    return True

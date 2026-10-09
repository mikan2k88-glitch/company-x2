"""Read-only contact preflight. Never claims or posts a contact."""
import os,re,urllib.error
from datetime import datetime,timezone
from .outreach import GitHubContact,status

def check(env=None,client=None):
    env=os.environ if env is None else env
    configured=status(env)
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'connection_ok':False,
      'sending_enabled':configured['ready'],'checks':[],
      'notice':'接続検査は送信しません。権限情報が正常でも、実際の投稿成功を保証するものではありません。'}
    def add(code,ok,message):result['checks'].append({'code':code,'ok':ok,'message':message})
    if not env.get('GITHUB_OUTREACH_TOKEN'):
        add('token',False,'GITHUB_OUTREACH_TOKENをRenderに登録してください。');return result
    login=env.get('GITHUB_OUTREACH_LOGIN','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,39}(?:\[bot\])?',login):
        add('login',False,'GITHUB_OUTREACH_LOGINに送信専用トークンのユーザー名を設定してください。');return result
    if not configured['repos']:
        add('repositories',False,'OUTREACH_GITHUB_REPOSに許可済みのowner/repoを1〜5件指定してください。');return result
    client=client or GitHubContact(env)
    try:
        identity=client.api('/user')
        if not isinstance(identity,dict) or str(identity.get('login','')).lower()!=login.lower():
            add('identity',False,'トークンのユーザーとGITHUB_OUTREACH_LOGINが一致しません。');return result
        add('identity',True,'送信者の認証ユーザーが一致しました。')
        for repo in configured['repos']:
            data=client.api('/repos/'+repo)
            valid=isinstance(data,dict) and str(data.get('full_name','')).lower()==repo
            usable=valid and data.get('has_issues') is True and not data.get('archived') and not data.get('disabled')
            add('repository:'+repo,usable,repo+('へのアクセスとIssuesが有効です。Issues書き込み権限はトークン設定で別途確認してください。' if usable else 'にアクセスできないか、Issuesが無効・アーカイブ済みです。'))
        result['connection_ok']=all(x['ok'] for x in result['checks'])
    except urllib.error.HTTPError as exc:
        message={401:'GitHub認証が拒否されました。専用トークンを確認してください。',403:'GitHub権限または呼び出し制限により検査できません。',404:'対象リポジトリが存在しないか、トークンで参照できません。'}.get(exc.code,'GitHubの応答エラーで検査できません。')
        add('github',False,message)
    except Exception:
        add('github',False,'接続を確認できません。時間をおいて再検査してください。')
    return result

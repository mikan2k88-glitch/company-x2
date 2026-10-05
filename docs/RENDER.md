# E02: Render + Supabase 試作

この区切りは、パスワード付きの無料検証画面をRenderで起動し、Supabaseに案件・イベント・成果物を保存する実装です。
AI・実決済・営業送信はまだ接続しません。HTTPサーバーは限定試作向けで、一般公開の有料サービス向けではありません。

## 1. Supabase

SQL Editorで `supabase/migrations/002_sandbox_rpc.sql` を実行してください。
002は単独で実行できます。001は将来の実取引用定義で、今回の試作には不要です。
Company X2専用スキーマとpublic.cx2_store関数を作成します。既存アプリのテーブルは変更しません。
関数を呼べるのはservice_roleのみです。anonやpublishableキーでは接続できません。
既存Supabaseプロジェクトを使う場合、同じ管理キーには他アプリへの権限もあるため、キーはサーバー環境変数だけに保存します。

## 2. Render Web Service

| 項目 | 値 |
|---|---|
| Repository | mikan2k88-glitch/company-x2 |
| Branch | main |
| Runtime | Python 3 |
| Root Directory | 空欄 |
| Build Command | python -m compileall -q company_x2 |
| Start Command | python -m company_x2.server |
| Health Check Path | /api/health |

RenderのPORTを自動使用し、0.0.0.0で待ち受けます。独自ドメインはALLOWED_HOSTSに追加します。
今回の実装は1サービスの小規模試作です。スケールや一般公開の前に本番用HTTPサーバーと入場制御を整備します。

## 3. 環境変数

| 名前 | 内容 |
|---|---|
| STORAGE_BACKEND | supabase |
| SUPABASE_URL | https://プロジェクトID.supabase.co |
| SUPABASE_SECRET_KEY | sb_secret_で始まるサーバー用Secretキー |
| APP_ACCESS_TOKEN | 32文字以上の十分にランダムな試作アクセス用パスワード |
| ADMIN_TOKEN | 32文字以上の別のランダムな管理API用トークン（管理APIを使う場合） |
| ALLOWED_HOSTS | 通常は不要。独自ドメイン使用時はホスト名をカンマ区切りで設定 |

旧service_roleキーを使う場合はSUPABASE_SECRET_KEYの代わりにSUPABASE_SERVICE_ROLE_KEYへ設定してください。
SUPABASE_ANON_KEYやpublishableキーは使用しません。両方の管理キーを設定した場合はSUPABASE_SECRET_KEYを優先します。
RENDER_EXTERNAL_HOSTNAMEはRenderが提供し、許可ホストに自動追加します。
キーとアクセスパスワードをREADME、ブラウザコード、GitHubへ書かないでください。

## 4. 起動と確認

SQLを適用して環境変数を保存した後にデプロイします。キーだけではテーブルや関数は作成されません。
URLを開くとBasic認証の入力が出ます。ユーザー名はdemoなど任意、パスワードはAPP_ACCESS_TOKENの値です。
サンプルCSVを送信し、制作完了とダウンロードを確認します。
GET /api/healthが以下を返すことを確認します。

```json
{"status":"ok","endpoint":"E02","mode":"sandbox","storage":"supabase","payments_enabled":false,"outreach_enabled":false,"ai_connected":false}
```

再デプロイ後、同じタブの案件が読み取れることを確認します。案件トークンはsessionStorageに保持され、タブを閉じると失われる場合があります。
処理中に停止した案件は120秒のlease期限後に別workerが取得でき、最大3試行で終了します。古いworkerは新しいclaimの完了を書き込めません。

## 接続失敗

設定不足、schema不一致、鍵の権限不足は起動エラーになります。起動後に接続不能になった場合は503を返します。
SQLiteへの自動切り替えは行いません。キーや入力内容は接続エラーに出力しません。
healthはDBへアクセスするため、失敗中はRenderのhealth checkも不合格になります。

## 残る作業

本番SupabaseへのSQL適用とRender実環境での確認は、コードのCI検証とは別です。
試作データの保持期限・削除、顧客アカウント、レート制限、本番HTTPサーバー、AI・営業経路・決済は次の開発対象です。

参考: https://render.com/docs/web-services / https://supabase.com/docs/guides/getting-started/api-keys

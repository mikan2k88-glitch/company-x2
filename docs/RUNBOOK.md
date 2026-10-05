# ローカル試作の起動と検証

Python 3.12以上。追加ライブラリは不要です。リポジトリのルートで実行します。

```sh
python -m unittest discover -s tests -v
python -m company_x2.server --port 8080
```

http://127.0.0.1:8080 を開き、CSVを入力して条件に同意します。
受付→制作・検品→結果ダウンロードまで自動処理されます。無料のsandboxで、AIや決済は呼びません。
同じタブを更新するとsessionStorageの案件情報で状態を再取得します。
入力は処理終了時に消去し、成果物はSQLiteに保存します。案件アクセスには顧客トークンが必要です。
トークンを失った案件の復旧、データ保持期限と削除は未実装です。機密データを投入しないでください。

## 営業候補の取り込み

許可済みの取得経路からJSONを供給するアダプターを次に実装します。現在はファイル入力までです。

```sh
python -m company_x2.scout listings.json
```

形式:
```json
[
  {
    "source": "actual-provider-name",
    "external_id": "provider-job-id",
    "url": "https://provider.example/jobs/123",
    "title": "CSVの完全一致重複除去",
    "service_key": "csv_exact_dedup",
    "budget_jpy": 1000,
    "estimated_cost_jpy": 100,
    "automated_proposals_allowed": false
  }
]
```

この例は形式説明用で、実在案件ではありません。sourceとexternal_idで重複を抑制します。
取得元の真正性・期限・自動応募条件はまだ検証できません。qualifiedは受注済みを意味しません。
自動提案の許可がない候補はblockedになります。どの候補にも営業送信しません。
ローカル管理APIは起動時に表示する管理トークンをX-Admin-Tokenヘッダーに使用します。
GET /api/opportunities で一覧、POST /api/opportunities で1件の取り込みができます。

## 運用範囲

- 127.0.0.1専用。公開用のサーバーではありません。
- 同じDBに対して起動するプロセスは1つのみ。別ポートで同じDBを使わないでください。
- 制作は外部副作用のないCSV処理。起動時に中断案件を再キューします。
- 実決済・営業送信・AIは未実装です。売上は常に0円です。
- 本番前に認証、アップロード制限、保持期限、処理数制限、HTTPS、永続化アダプターを追加します。
- CSVの値は保持されるため、表計算ソフトへの数式注入を防ぐ出力仕様を本番前に確定します。
- Supabase保存アダプターはE02で実装。設定はdocs/RENDER.md参照。SQLiteとの同期はありません。

## 次の実装

1. 自動取得・提案が可能な実在の案件供給元を決定する。
2. Supabaseで永続化・競合更新・イベント記録を実装する。
3. AIによる依頼理解と提案を、決定済みの業務範囲に限定して接続する。
4. sandbox決済と納品を接続し、二重請求・通信結果不明・取消・返金を検証する。
5. 本番条件を設定して有料案件1件を実証する。

# Gemini接続とフォールバック

Renderに `AI_PROVIDER=gemini`、`GEMINI_API_KEY` を設定します。既存の
`AI_ENABLED=true`、`AI_MONTHLY_BUDGET_MICRO_USD=3000000`、
`AI_DAILY_BUDGET_MICRO_USD=100000` は共通の予算台帳で引き継ぎます。
追加SQLは不要です。AIキーはサーバーにのみ保存し、ブラウザーへ返しません。

主系は `gemini-3.8-flash`、代替は `gemini-3.7-flash`。
主系がHTTP 404・429・503を明示的に返した場合のみ代替を1回呼びます。
認証エラー、タイムアウト、通信結果不明、回答の切断、形式不正、安全ブロック、
非対応の依頼では再試行しません。両モデル失敗時は手動のサービス選択と
無料の作業計画作成を案内します。未知の依頼を自動で実行しません。

送信するのは同意した依頼文だけです。CSV・キー・顧客トークンはAIへ送りません。
外部ツール、検索、コード実行は与えません。Google側のデータ処理条件は契約に従います。
課金済みのGemini Developer APIプロジェクトのキーを使用してください。
Vertex AI用の認証は今回のアダプターでは利用しません。

同一所有者の同じ依頼には主系・代替を合わせた1つの予算予約を先に確保します。
予算が足りなければ外部APIへ接続しません。成功結果はキャッシュし、
失敗・処理中でも同じ依頼を再課金しません。失敗時にはモデル名と安全な結果状態を保存します。
1試行の出力上限1024、thinkingLevelはlow。料金予約は2027年の公表通常料金
（入力$1.50・出力$7.50/100万トークン）を使用し、2026年の導入料金より多めに確保します。
UTF-8送信バイト数に4096の入力余裕を加え、最大2試行分を予約します。
未使用の代替分や失敗分も返還しないため、実請求額より予約額が大きくなります。
将来の料金変更は別途見直しが必要です。アプリ外の利用料は対象外です。

設定後は `/company` の「状態を更新」でGemini接続設定済みを確認します。
「CSVをJSONに変換してください」の依頼文とAI送信同意で判断を試してください。
結果に使用モデルが表示されます。対応候補が返っても、計画と同意が揃うまで制作しません。

OpenAIアダプターは `AI_PROVIDER=openai` と `OPENAI_API_KEY` で利用可能ですが、
GeminiからOpenAIへの自動切り替えは行いません。

公式仕様（2026-10-08確認）:
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/pricing

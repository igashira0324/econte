# econte

**AI動画パイプラインのための、ストーリーボード・スキーマ + ローカル生成ツールチェーン**

*[English README](README.md)*

econte は、ストーリーボード（絵コンテ）をAI動画制作の真実源として扱うためのツールです。
キャラクター・グローバルスタイル・ショット・カメラ指示・歌詞/ビート同期・機械可読な承認ゲートを
1つのJSONファイルに持たせ、それを元に手持ちのComfyUIモデルでキーフレームや動画クリップを生成し、
結果をストーリーボードへ書き戻すところまでを一気通貫で扱います。

このプロジェクトが存在する理由: 2026年時点、絵コンテの標準交換形式は業界に存在せず、
承認ゲート付きでオフライン/ローカル完結する生成ツールチェーンも存在しません。
商用のAI絵コンテツール(LTX Studio, Google Flow等)はデータを自社製品内に閉じ込め、
実在する「脚本→絵コンテ→動画」のOSSエージェント(ViMax, VideoClaw等)はいずれもクラウドAPI
専用で、コンシューマGPU上のローカルComfyUIバックエンドを対象にしたものはありません。
この調査の詳細は [`docs/why.md`](docs/why.md) を参照してください。

## 同梱物

| パッケージ | 役割 |
|---|---|
| [`spec/`](spec/) | 正規スキーマ `econte.schema.json` (JSON Schema 2020-12)。TypeScript側から自動生成 |
| [`packages/econte`](packages/econte/) | TypeScript/Zod スキーマ + バリデータ (真実源) |
| [`python/econte`](python/econte/) | pydantic 鏡像 + CLI: `validate` / `compile` / `run` / `ingest` / `sheet` |
| [`profiles/`](profiles/) | バックエンドプロファイル。econte のマニフェストを**自分の**ComfyUIワークフローに接続するデータ定義(特定モデル専用ではない) |
| `examples/haruka/` | **計画中・未実装** — 権利的にクリーンなオリジナルキャラによる、8ショットのストーリーボード実例。`CHANGELOG.md`参照 |

## パイプライン

```
storyboard.json (キャラ・ショット・カメラ・歌詞/ビート同期・approved: false)
       │
       │ econte compile --target keyframes
       ▼
キーフレーム発注書 → econte run → キーフレームPNG (手持ちモデル)
       │
       │ econte sheet (自己完結HTML承認シート)
       ▼
   人間による承認 (approved: true へ、または --only <id> でリテイク)
       │
       │ econte compile --target clips (承認済みキーフレームのみ)
       ▼
動画発注書 → econte run → 動画クリップ (手持ちモデル)
       │
       │ econte ingest
       ▼
storyboard.json を実ファイルパスで更新 (実尺は書き込まない、下記参照)
```

`econte ingest` は測定済みの実尺を意図的に書き込みません。納品書の時間情報は
「生成にかかった時間」であって「メディアの実尺」とは別物で、混同すると誤った
秒数がそのまま書き込まれてしまいます。実尺の測定(ffprobe等)は別の後段ツールの
役割として切り出しています — 詳細は `docs/compile-spec.md` の
「Scope boundary」節を参照。

特定モデルへの依存はありません。`profiles/` がComfyUIグラフとマニフェストの
フィールド対応を記述する仕組みで、Qwen-Image-Edit(キーフレーム)とMiniMax H3 Motion
Context(動画)の2つのリファレンスプロファイルは「対応バックエンドの例」であって
それだけに限定されるものではありません。

## 現状

開発初期段階(v0.1.0を目標)。1.0.0までスキーマは変更され得ます(`CHANGELOG.md`参照)。
Issue・小さく焦点を絞ったPRを歓迎します(`CONTRIBUTING.md`参照)。

## ライセンス

Apache-2.0 — [`LICENSE`](LICENSE) / [`NOTICE`](NOTICE) を参照。

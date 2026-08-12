# ストーリーボード駆動・動画生成ツールチェーン OSS化 実装プラン

作成: 2026-08-13 ／ 対象: storyboard.json スキーマ + マニフェスト駆動生成ハーネスの一般公開

---

## 0. 何を公開するか（プロダクト定義）

**「絵コンテ(storyboard.json)を真実源として、ローカル生成 → 人間承認 → 編集 を回すためのスキーマ + ツールチェーン」**

調査(2026-08-13)で確認した空白領域そのもの:

- 絵コンテの標準交換形式は業界に存在しない（PDF/CSV/独自JSONが乱立）
- `approved`（承認ゲート）と `lyric`（歌詞同期）を一級市民で持つOSSは皆無
- ローカルComfyUI（12GB級GPU）を絵コンテから駆動する汎用OSSも皆無
  （ViMax/VideoClaw はクラウドAPI専用、ComfyUI系UIはツール内独自形式）

### 3本柱

| 柱 | 内容 | 元になる実装 |
|---|---|---|
| **1. Schema** | storyboard スキーマ（canonical JSON Schema + TS/Zod + Python/pydantic の3点セット） | remotion側 storyboard.json v1 (Zod設計) |
| **2. Runners** | マニフェスト駆動のComfyUIハーネス（静止画キーフレーム / 動画クリップ）。バックエンドは**プロファイル**として差し替え可能 | `keyframe_runner.py` / `h3_chain_runner.py` |
| **3. Converters & Sheets** | storyboard→発注書コンパイラ、納品書(keyframes.json/clips.json)→storyboard書き戻し、承認シートHTML生成 | `build_storyboard.py` + clips.json 実装 |

### 非ゴール（v1では作らない）

- GUIエディタ（承認はHTML+JSON編集で回す。エディタは需要が見えてから）
- クラウド生成バックエンド（Veo等。プロファイル機構だけ拡張可能に設計しておく）
- ビート解析（librosaはremotion側の責務のまま。analysis.json への**参照**だけ持つ）
- Remotionコンポーネント（編集表現は各自のプロジェクト側）

---

## 1. リポジトリ・名前・ライセンス

### 名前（要決定 → Phase 0 で空き確認）

| 候補 | 根拠 | 懸念 |
|---|---|---|
| **econte**（推奨） | 絵コンテ。短い・由来が明確・日本発を示せる。`*.econte.json` | npm/PyPIの空き未確認 |
| conteflow | conte+flow、動画生成フローを示唆 | やや説明的 |
| storyboard-manifest | 検索に強い説明的名前 | 長い・無個性 |

### ライセンス: **Apache-2.0 を推奨**

- 特許条項つきで企業ユーザーも採用しやすい（OTIO, video-notation-schema と同系）
- ComfyUIとはHTTP API越しの通信のみなのでGPL汚染なし
- **注意**: LTX Director / MiniMaxH3-Director / Velorn は GPL-3.0。**コードのコピーは一切禁止**（データ形式の相互運用のみ）

### リポジトリ構成（モノレポ1つ、新規作成）

```
econte/                          # (仮名)
├── spec/
│   ├── econte.schema.json       # canonical JSON Schema 2020-12 (CIで自動生成)
│   └── SCHEMA.md                # フィールド解説 (自動生成)
├── packages/econte/             # npm: Zodスキーマ(真実源) + validator + 型
├── python/econte/               # PyPI: pydanticモデル + runners + CLI
│   ├── models.py                # スキーマのPython鏡像
│   ├── runners/                 # comfyui_client, keyframes, clips
│   ├── compile.py               # storyboard → 発注書
│   ├── ingest.py                # 納品書 → storyboard 書き戻し
│   └── sheet.py                 # 承認シートHTML
├── profiles/                    # バックエンドプロファイル (データ、コードではない)
│   ├── qwen-image-edit-2511.yaml
│   ├── minimax-h3-motion-context.yaml
│   └── custom-workflow.md       # 自分のワークフローを繋ぐ手順書
├── examples/haruka/             # オリジナルキャラのサンプル一式 (§6)
├── docs/                        # quickstart (EN/JA), architecture, 移行ガイド
└── .github/workflows/ci.yml    # Windows + Linux
```

**既存の私的プロジェクト(作品データ含み)は公開しない**。新規リポジトリへ**クリーンに抽出**し、git履歴の漏洩リスクをゼロにする。

---

## 2. 設計の要点（決定事項と推奨）

### D1. スキーマの真実源は Zod（TS）

remotion側P1が既にZodで設計中のため二重管理を避ける。CIで `zod-to-json-schema` により canonical JSON Schema を生成し、Python側は pydantic の手書き鏡像 + **TS↔Py 相互検証のゴールデンテスト**（同じサンプルを両方で検証し合格/不合格が一致すること）で同期を担保。

### D2. スキーマ拡張（v1 → 公開版 0.x）

現行v1（metadata / characters / globalStyle / audioAnalysis / scenes.shots{camera, source, lyric}）に生成ラウンドトリップ用のフィールドを追加:

```jsonc
"shots": [{
  "id": "S01-A",
  // ... 既存: idea/subject/action/camera/heroMotion/audioSync/lyric ...
  "source": {
    "type": "generate | asset | remotion",
    "backend": "qwen-image-edit-2511",     // 追加: プロファイルID
    "keyframe": "keyframes/S01-A.png",
    "seed": 55501,                          // 追加: 再現性
    "prompt": "...", "approved": false,
    "material": "chain | chain_start | standalone"  // 追加: H3連鎖セマンティクス
  },
  "render": {                               // 追加: 納品書からの書き戻し先
    "file": "clips/S01-A.mp4",
    "actualSeconds": 4.25, "renderedAt": "..."
  }
}]
```

- `version` はセマンティックバージョン。0.x の間は破壊的変更可、1.0 でフリーズ宣言
- ト書き=日本語 / prompt=英語 の分離は現行設計のまま文書化（i18nの強み）

### D3. バックエンドプロファイル = 「データとしてのワークフロー」

汎用性の核。**プロファイル = ComfyUI APIフォーマットのグラフJSON + プレースホルダ写像 + 制約 + コストモデル**:

```yaml
id: minimax-h3-motion-context
kind: video
capabilities: { chain: true, per_slot_ref: true, fast_flag: true }
constraints: { resolution_multiple: 32, notes: "2本目の連鎖クリップで初めて落ちる" }
cost: { min_per_clip: 13.5, fast_multiplier: 1.8, origin_s: 5.167, chained_s: 4.25 }
server: { default_port: 8189 }
workflow: { template: h3_ref2v.json, bindings: { "6.inputs.image": "$ref_image", ... } }
```

ユーザーは自分のComfyUIワークフローを「APIフォーマットで書き出し → bindings を書く」だけで任意モデルを接続できる（調査で見た AI-storyboard-generator の WanSE.json 方式の一般化）。検証済みの実測値（40秒/枚、13.5分/クリップ等）はプロファイルの `cost` に載り、dry-run 見積もりに使われる。

### D4. CLI（Python側に集約）

```bash
econte validate <storyboard.json>                 # スキーマ検証
econte compile <sb> --target keyframes|clips      # 発注書生成 (承認済みのみ等のフィルタ付き)
econte run <manifest> [--dry-run] [--only ID...]  # 生成実行 (ComfyUI)
econte ingest <sb> --report <..._clips.json>      # 実尺・ファイルパスを書き戻し
econte sheet <sb> -o approval.html                # 承認シート生成 (base64サムネ自己完結型)
```

### D5. Windowsファースト

開発環境がWindowsなのでCIは **windows-latest + ubuntu-latest の両方**。既知の罠をテスト化: モデルパスのバックスラッシュ（`qwen\...` — 今日実際に踏んだHTTP 400）、cp932コンソール、CRLF。依存は pydantic + 標準ライブラリ中心に薄く保つ。

### D6. テスト戦略（GPUなしCIで生成ロジックを守る）

- スキーマ: valid/invalid のゴールデンファイル群（TS/Py両方で実行）
- コンパイラ/書き戻し: スナップショットテスト
- ランナー: **モックComfyUIサーバー（record/replay）**。実機で一度 `/prompt`→`/history` の実応答を記録し、CIでは再生。実GPUスモークはリリース前に手元で `examples/` を1周
- Lint/型: ruff + mypy / eslint + vitest

---

## 3. 実装フェーズ（合計 6〜9 作業日、大半は本セッション系で実行可能）

| Phase | 内容 | 完了条件 (DoD) | 目安 |
|---|---|---|---|
| **P0** | 名前の空き確認(npm/PyPI/GitHub)、リポジトリ作成、Apache-2.0、CI骨格、README雛形 | CIが空テストでグリーン | 0.5日 |
| **P1** | Schemaパッケージ: v1移植+D2拡張、JSON Schema自動生成、pydantic鏡像、相互ゴールデンテスト、`econte validate` | 相互検証テスト合格、サンプルsb検証OK | 1〜2日 |
| **P2** | Runners一般化: プロファイルローダ、keyframes/clipsランナー（keyframe_runner/h3_chain_runnerから抽出・汎用化）、dry-run見積もり、納品書出力、record/replayテスト | モックCIグリーン + 実機で8カット再生成一致 | 2〜3日 |
| **P3** | Converters: `compile`（承認フィルタ・チェーングループ計算込み）/ `ingest` / `sheet`（build_storyboard.py汎用化） | 先行検証と同等構成(8ショット・メイン連鎖+寄り+B-roll混在)をharukaで一周 | 1〜2日 |
| **P4** | examples/ をオリジナルキャラで作成（§6）、docs（quickstart EN/JA・architecture図・「自分のワークフローを繋ぐ」手順）、実GPUスモーク | 新規ユーザー視点でREADMEだけで一周できる | 1日 |
| **P5** | 公開: public化、v0.1.0タグ、(任意)npm/PyPI公開、告知記事 | リリースノート公開 | 0.5日 |

### その後のロードマップ

- **v0.2**: Fountain importer（歌詞/台本→scenes雛形）、Multiple Angles / Next Scene LoRA対応プロファイル、`--retake`運用の洗練
- **v0.3**: OTIO exporter（DaVinci等への出口）、MiniMaxH3-Director タイムラインJSON⇄econte コンバータ（相互運用、コード非接触）
- **v1.0**: スキーマフリーズ、互換性ポリシー明文化

---

## 4. 既存プロジェクトの移行（ドッグフーディング）

| プロジェクト | 移行内容 | 時期 |
|---|---|---|
| Remotion側の動画編集プロジェクト | 自前の `storyboard/schema.ts` を npm パッケージ import に置換（P1完了後）。キーフレーム生成のローカル経路が `econte compile/run` を呼ぶ | P1後 |
| ComfyUIハーネス側の生成プロジェクト | `keyframe_runner.py`/`h3_chain_runner.py` は **v0.2でパリティ達成まで現状維持**。以後 `econte run --profile minimax-h3 --config <ローカル専用config>`（実パス等はリポジトリ外のローカルconfigへ、gitignore対象） | v0.2後 |

実プロジェクト(MV制作)が最初のユーザーになることで、スキーマの穴をリリース前に踏み抜く。

---

## 5. リスクと対策

| リスク | 対策 |
|---|---|
| 名前衝突・スクワット | P0で npm/PyPI/GitHub を確認してから一切の命名を確定 |
| スキーマがremotion P1と並行で揺れる | 0.xの間は破壊的変更OKと明示。1.0まで「実装が仕様」 |
| GPLコード混入 | GPL製近縁ツールはデータ形式の観察のみ。コードコピー禁止をCONTRIBUTINGに明記 |
| サンプル素材の権利 | §6のオリジナルキャラのみ。**Miku等の既存IP・実在人物参照は絶対にリポジトリに入れない** |
| ComfyUI APIの変化 | テスト済みComfyUIバージョン範囲をREADMEに明記。replayテストで検知 |
| 一人メンテの負荷 | 非ゴールの堅持。モデル対応は「プロファイル=データ追加」で済む設計が防波堤 |

### 公開前チェックリスト

- [ ] 個人パス（E:\ / F:\ / ユーザー名）がコード・docs・テストに残っていない
- [ ] APIキー・トークン類なし（新規リポジトリなので履歴リスクは構造的にゼロ）
- [ ] サンプル画像のメタデータ（EXIF/生成ワークフロー埋め込みPNG）を洗浄
- [ ] 既存IP・実在人物由来の素材ゼロ（サンプルはオリジナルキャラのみ）
- [ ] LICENSE / NOTICE / CONTRIBUTING / CHANGELOG / README(EN) / README.ja.md

---

## 6. サンプルプロジェクト「haruka」（examples/）

権利的にクリーンな**オリジナルキャラ1体**を Qwen-Image-2512 で新規作成（キャラバイブル: 正面図+identity一行）し、CC0で同梱:

- `haruka.storyboard.json` — 8ショット（メイン連鎖3 + 寄り2 + B-roll単発2 + 場面転換1 = 今日の検証構成の移植）
- `keyframes/` — 生成済みキーフレーム8枚（承認済み状態のデモ）
- `approval.html` — 承認シートの実物
- クリップ生成はコマンド例のみ（動画バイナリは同梱しない。リポジトリ肥大防止）

先行検証(社内テストキャラでの8ショット絵コンテ、40秒/枚・8/8成功・全ショット種で同一性維持)が
「これは実際に動く」という再現手順つきの実績になっている。同じ構成を haruka で再現し、
`examples/` に権利的にクリーンな形で同梱する。

---

## 7. 決定事項（2026-08-13 承認済み）

1. **名前**: **econte** — npm/PyPI/GitHub とも空きを確認済み
2. **ライセンス**: **Apache-2.0**
3. **公開範囲**: まず GitHub のみで開始（開発中は private、v0.1.0 リリース時に public 化）。npm/PyPI 公開は v0.2 以降
4. **ドキュメント言語**: 英語主 + 日本語併記（README.md / README.ja.md）
5. **GitHubアカウント**: 個人リポジトリ (igashira0324/econte)

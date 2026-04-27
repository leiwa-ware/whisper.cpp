# PoC フィジビリティ仕様書
**会議内容マルチレイアウト表示システム（Salesforce商談連携）**

---

## 目次

1. [背景・目的](#1-背景目的)
2. [解決すべき本質的な問題](#2-解決すべき本質的な問題)
3. [Classicアーキテクチャとの差異](#3-classicアーキテクチャとの差異)
4. [システム全体設計](#4-システム全体設計)
5. [推奨技術スタック（案1・案2）](#5-推奨技術スタック案1案2)
6. [AWSインフラ構成](#6-awsインフラ構成)
7. [Salesforce連携設計](#7-salesforce連携設計)
8. [意味的プロファイルスキーマ設計](#8-意味的プロファイルスキーマ設計)
9. [フロントエンド実装仕様](#9-フロントエンド実装仕様)
10. [バックエンドAPI仕様](#10-バックエンドapi仕様)
11. [データベーススキーマ](#11-データベーススキーマ)
12. [PoCで検証すべき4つの問い](#12-pocで検証すべき4つの問い)
13. [テスト戦略](#13-テスト戦略)
14. [実装フェーズ計画](#14-実装フェーズ計画)
15. [非機能要件](#15-非機能要件)
16. [用語定義](#16-用語定義)
17. [議事録生成方式の検討](#17-議事録生成方式の検討)

---

## 1. 背景・目的

### 1.1 背景

複数部門のユーザーが参加する会議において、参加者は立場・部門・役割に応じて異なる視点で会議内容を解釈する必要がある。

- **A部門ユーザー**：B部門のトピックは「参照情報」、C部門のトピックは「サイドバー情報」として認識
- **B部門ユーザー**：B部門のトピックが「主題」であり、他部門は背景情報
- **同一部門でも役割（リーダー／メンバー／オブザーバー）により必要な情報の粒度が異なる**

### 1.2 目的

Salesforce標準オブジェクト「商談（Opportunity）」をデータ基盤とし、同一の会議データを参加者の立場・部門・役割に応じて異なる表現形式で表示するWebシステムのフィジビリティをPoCで検証する。

### 1.3 参照モデル

Salesforceの「レコードタイプ（Record Type）× ページレイアウト（Page Layout）」の仕組みを外部Webシステムとして独自実装する。

---

## 2. 解決すべき本質的な問題

### 2.1 問題の本質（Classicとの差異）

従来のダッシュボードカスタマイズ（Grafana・react-grid-layout等）が解くのは：

> 「同じ情報を、**どこに・どのサイズで**置くか」（1次元の変更）

今回解くべき問題は：

> 「同じ会議データを、**参加者の立場・文脈に応じて意味的に再解釈**して見せる」（3次元の変換）

### 2.2 必要な3次元の変換

| 次元 | 内容 | Classicで対応可否 |
|------|------|-----------------|
| **表示形式** | カード型／タイムライン型／テーブル型／ミニ表示 | ✗ 不可 |
| **情報の粒度** | 見出しのみ／要約／詳細展開／完全表示 | ✗ 不可 |
| **文脈的強調** | 「主題」「参照」「背景」「非関連」の意味付け | ✗ 不可 |

### 2.3 Classicが対応できない理由

```
Classic（Grafana等）：
  データ → [位置・サイズJSON] → レンダリング
  ※ データの意味・解釈は固定

今回必要なもの：
  データ → [意味的プロファイルJSON] → コンポーネント選択 → レンダリング
  ※ 同一データが立場により「主題」にも「参照」にもなる
```

---

## 3. Classicアーキテクチャとの差異

| 比較軸 | Classic（Grafana等） | SF Page Layout | 今回必要なもの |
|--------|---------------------|----------------|---------------|
| 変更の対象 | 位置・サイズ・表示順 | フィールドの表示/非表示・並び順 | 表示形式・粒度・意味的文脈すべて |
| データの解釈 | 固定（同じ値を見る） | 固定（同じフィールドを見る） | 立場により「主題」か「参照」かが変わる |
| コンポーネント型 | ウィジェット型固定 | フォームフィールド固定 | 同一トピックを複数UIコンポーネント型で表現 |
| 粒度の制御 | なし（表示/非表示のみ） | フィールドレベルのみ | 要約のみ／詳細展開可／完全展開を立場で制御 |
| 継承モデル | ユーザー設定の上書きのみ | Profile × RecordType の2軸 | デフォルト→部門→役割→個人 の4階層継承 |
| 権限との分離 | 表示＝権限（混在） | FLS（フィールド権限）で分離 | UX縮小表示 と セキュリティ非表示 を別レイヤーで管理 |

---

## 4. システム全体設計

### 4.1 3層アーキテクチャ

```
┌─────────────────────────────────────────────┐
│  データ層（会議コンテンツ）                        │
│  ・Salesforce Opportunity オブジェクト           │
│  ・トピックID・発言記録・アクション・部門タグ          │
└───────────────────┬─────────────────────────┘
                    │ REST API Pull（JWT Bearer）
┌───────────────────▼─────────────────────────┐
│  プロファイル定義層（意味的レイアウト定義）            │
│  ・部門 × 役割 ごとの意味的プロファイルJSON          │
│  ・継承チェーン：デフォルト→部門→役割→個人           │
│  ・コンポーネント型・粒度・文脈強調を定義             │
└───────────────────┬─────────────────────────┘
                    │ コンポーネントディスパッチ
┌───────────────────▼─────────────────────────┐
│  レンダリング層（フロントエンド）                    │
│  ・コンポーネントレジストリ                        │
│  ・プロファイルに基づく動的コンポーネント選択          │
│  ・ドラッグ&ドロップによる個人カスタマイズ            │
└─────────────────────────────────────────────┘
```

### 4.2 データと表示定義の分離原則

- **会議データ（コンテンツ）**：Salesforce Opportunityオブジェクトに格納。部門タグ・トピック種別を持つ。変更不可（読み取り専用）。
- **レイアウトプロファイル（表示定義）**：PoC用PostgreSQL DBに格納。部門・役割単位で管理。
- **個人カスタマイズ**：ベースプロファイルからの差分のみを保存。ベースプロファイルを汚染しない。
- **権限情報**：レイアウトプロファイルとは別テーブルで管理。表示制御と混在させない。

### 4.3 画面構成（4画面）

UIモック実装を経て、当初の2画面構成から以下の4画面構成に拡張された。

```
[会議・訪問記録一覧 /list]
  │  会議カードをクリック            訪問カードをクリック
  ▼                                 ▼
[商談詳細 /detail]            [訪問詳細 /visit]
  ビュー切り替えタブ（3ビュー）      ビュー切り替えタブ（3視点）
  ・企画部ビュー                     ・フィールド担当者ビュー
  ・営業担当者ビュー                  ・マネージャービュー
  ・営業改革推進部ビュー              ・データ品質ビュー
  │
  ▼（「議事録 →」ボタン）
[議事録 /minutes]
  Markdown形式の議事録レンダリング
  → 「商談データを確認する →」で /detail に戻る
```

| 画面名 | パス | 主なプロファイル制御対象 |
|--------|------|----------------------|
| 会議・訪問記録一覧 | `/list` | なし（全員共通） |
| 商談詳細 | `/detail` | 3部門ビュー切り替え |
| 訪問詳細 | `/visit` | 3視点ビュー切り替え |
| 議事録 | `/minutes` | なし（全員共通） |

---

## 5. 推奨技術スタック（案1・案2）

### 5.1 案1（推奨：Node.js構成）

| 層 | 技術 | 選定理由 |
|----|------|---------|
| クラウド | AWS (ap-northeast-1) | 実績・エコシステム |
| フロントエンド | React + Vite (SPA) | コンポーネントレジストリ実装に最適 |
| バックエンド | Node.js (Express) | SF REST APIのJSONレスポンスをそのまま扱いやすい。`jsforce`ライブラリが充実 |
| DB | Amazon RDS PostgreSQL | SF商談オブジェクトのリレーショナル構造を模倣できる |
| キャッシュ | Amazon ElastiCache (Redis) | SF APIコール節約（TTL 5〜10分） |
| 秘密管理 | AWS Secrets Manager | SF秘密鍵・Client IDの安全管理 |
| 配信 | CloudFront + S3 | 静的アセット配信 |
| コンテナ | ECS Fargate | バックエンドの運用コスト最小化 |

### 5.2 案2（Python構成）

案1との差分のみ記載：

| 層 | 技術 | 案1からの変更理由 |
|----|------|----------------|
| バックエンド | Python (FastAPI) | `simple-salesforce`ライブラリがSF連携で最も充実。AI処理拡張時に有利 |

> **選択基準**：チームにPython習熟者が多い場合は案2、Node.js習熟者が多い場合は案1。将来的にAI処理（レイアウト自動推薦等）を追加する場合は案2を推奨。

---

## 6. AWSインフラ構成

### 6.1 構成図（テキスト表現）

```
[ブラウザ]
    │ HTTPS
    ▼
[CloudFront] ──── /api/* ────▶ [ALB]
    │                              │
    ▼                              ▼
[S3 Bucket]              [ECS Fargate]
(ビルド成果物)            (案1: Node.js / 案2: FastAPI)
                              │              │
                              ▼              ▼
                    [ElastiCache Redis]  [RDS PostgreSQL]
                    (SF APIキャッシュ)    (レイアウトプロファイル)
                              │
                   ┄┄┄┄参照┄┄┄┄▶ [Secrets Manager]
                                    (SF秘密鍵 / Client ID)

                    ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
                              │ JWT Bearer Flow
                              ▼
                    [Salesforce Sandbox/Production]
                    ├── Connected App (OAuth 2.0 JWT Bearer)
                    ├── Opportunity オブジェクト
                    ├── REST API (/services/data/vXX)
                    └── Profile / Role（部門・役割情報）
```

### 6.2 ネットワーク構成

- ECS Fargate・RDS・ElastiCacheは **Private subnet** に配置
- ALBのみPublic subnetに配置
- CloudFront → ALB間はHTTPS（ACM証明書）
- ECS TaskRoleにSecrets Manager読み取り権限（`secretsmanager:GetSecretValue`）を付与

### 6.3 PoC規模の目安

| リソース | PoC推奨設定 |
|---------|------------|
| ECS Fargate | 0.25 vCPU / 0.5GB RAM × 1タスク |
| RDS PostgreSQL | db.t3.micro（シングルAZ） |
| ElastiCache Redis | cache.t3.micro（シングルノード） |
| CloudFront | PriceClass_100（北米・欧州・アジア） |

---

## 7. Salesforce連携設計

### 7.1 Connected App セットアップ手順

#### Step 1: Developer Edition / Sandbox の用意

- PoC期間中は必ずSandbox環境を使用。本番orgへのConnected App作成はリリース時まで禁止。
- 必要権限：「システム管理者」プロファイル

#### Step 2: RSA鍵ペア生成（ローカル実行）

```bash
# 秘密鍵を生成
openssl genrsa -out private_key.pem 2048

# 自己署名証明書を生成（10年有効）
openssl req -new -x509 -key private_key.pem \
  -out certificate.crt -days 3650 \
  -subj "/CN=poc-sf-jwt"
```

> **重要**：`private_key.pem` は `.gitignore` に追加必須。Gitリポジトリへのコミット禁止。

#### Step 3: Connected App作成（SF管理コンソール）

| 設定項目 | 値 |
|---------|---|
| Connected App名 | `PoC Layout Viewer` |
| コールバックURL | `https://login.salesforce.com/services/oauth2/callback` |
| OAuthスコープ | `api`, `refresh_token` |
| デジタル署名 | `certificate.crt` をアップロード |

保存後、**Consumer Key（Client ID）** を記録する。

#### Step 4: アクセスポリシー設定（必須）

| 設定項目 | 値 | 注意 |
|---------|---|------|
| 許可されているユーザー | **管理者が承認したユーザーは事前承認済み** | これを設定しないとJWT Bearer Flowがエラーになる |
| IP制限の緩和 | すべてのユーザーに対してIP制限を緩和 | PoC期間中のみ |
| プロファイルの許可 | バックエンドが使用するユーザーのプロファイルを追加 | |

#### Step 5: AWS Secrets Managerへの秘密鍵登録

```bash
aws secretsmanager create-secret \
  --name "poc/salesforce" \
  --secret-string '{
    "client_id": "YOUR_CONSUMER_KEY",
    "username": "sf-service@example.com",
    "login_url": "https://test.salesforce.com",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\n..."
  }'
```

#### Step 6: JWT Bearer Flow 実装

**案1 — Node.js (`jsforce`)**

```javascript
import jsforce from 'jsforce';

const conn = new jsforce.Connection({
  oauth2: {
    loginUrl: process.env.SF_LOGIN_URL,
    clientId: process.env.SF_CLIENT_ID,
    redirectUri: 'https://login.salesforce.com/services/oauth2/callback',
  }
});

await conn.authorize({
  grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
  assertion: buildJwt(privateKey, clientId, username, loginUrl),
});
```

**案2 — Python (`simple-salesforce`)**

```python
import jwt, time, requests
from simple_salesforce import Salesforce

payload = {
    'iss': CLIENT_ID,
    'sub': SF_USERNAME,
    'aud': 'https://test.salesforce.com',
    'exp': int(time.time()) + 300,
}
assertion = jwt.encode(payload, PRIVATE_KEY, algorithm='RS256')

r = requests.post('https://test.salesforce.com/services/oauth2/token',
    data={
        'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        'assertion': assertion
    })

sf = Salesforce(
    instance_url=r.json()['instance_url'],
    session_id=r.json()['access_token']
)
```

### 7.2 データ取得仕様

#### 商談データ取得SOQL

```sql
SELECT
  Id,
  Name,
  StageName,
  Amount,
  OwnerId,
  Owner.Department,
  Owner.UserRole.Name,
  CloseDate,
  Description
FROM Opportunity
WHERE IsClosed = false
ORDER BY CloseDate ASC
LIMIT 50
```

#### データ同期パターン（PoC推奨）

| パターン | PoC採用 | 理由 |
|---------|---------|------|
| REST API Pull（リアルタイム） | **採用** | 実装シンプル。SF側変更が即反映。 |
| Bulk API（定期バッチ） | 将来拡張 | 大量データ時に検討 |
| Platform Events / CDC | 将来拡張 | 設定コスト高。PoC初期には過剰 |

#### Redisキャッシュ設定

```
キーフォーマット: sf:opportunities:{orgId}
TTL: 300秒（5分）
更新戦略: Cache-Aside（キャッシュミス時にSF APIを呼び出し再格納）
```

> **APIコール上限**：Salesforce Developer EditionはAPIコール数が1日1,000〜5,000程度と少ないため、Redisキャッシュは必須。

---

## 8. 意味的プロファイルスキーマ設計

### 8.1 設計思想

従来のレイアウトJSON（x/y/w/h）ではなく、各トピックに対して「この立場の人にとって、このトピックはどういう意味を持ち、どのコンポーネントで表示するか」を定義する。

### 8.2 プロファイルJSONスキーマ

```json
{
  "$schema": "https://example.com/layout-profile/v1",
  "profileId": "dept_営業__role_メンバー",
  "label": "営業部門 / メンバー",
  "baseProfileId": "dept_営業__default",
  "gridColumns": 2,
  "topics": [
    {
      "topicId": "competitive_alert",
      "role": "primary",
      "component": "CardFull",
      "granularity": "full",
      "position": { "order": 1, "span": 2 },
      "visibility": "visible"
    },
    {
      "topicId": "bant_info",
      "role": "reference",
      "component": "CardSummary",
      "granularity": "summary",
      "position": { "order": 4, "span": 1 },
      "visibility": "visible"
    },
    {
      "topicId": "timeline_year1",
      "role": "reference",
      "component": "TimelineItem",
      "granularity": "full",
      "position": { "order": 2, "span": 2 },
      "visibility": "visible"
    },
    {
      "topicId": "year_plan_bg",
      "role": "background",
      "component": "CardMini",
      "granularity": "title_only",
      "position": { "order": 5, "span": 2 },
      "visibility": "collapsed"
    },
    {
      "topicId": "action_sales",
      "role": "reference",
      "component": "ActionList",
      "granularity": "summary",
      "position": { "order": 3, "span": 2 },
      "visibility": "visible"
    }
  ]
}
```

> **トピック ID 対応表（営業担当者ビュー）**
>
> | topicId | 表示名 | role | component |
> |---------|--------|------|-----------|
> | `competitive_alert` | 競合の動きに要注意 | primary | CardFull |
> | `timeline_year1` | 2025年 進行中の打ち手 | reference | TimelineItem |
> | `action_sales` | ネクストアクション | reference | ActionList |
> | `bant_info` | 顧客情報（BANT+CH） | reference | CardSummary |
> | `year_plan_bg` | 2026・2027年計画 | background | CardMini |
>
> **その他のビューで使用するトピック ID**
>
> | topicId | 表示名 | 主なビュー | role |
> |---------|--------|----------|------|
> | `market_insight` | 市場・施策インサイト | 企画部: primary | primary |
> | `competitive_env` | 競合・市場環境 | 企画部: reference | reference |
> | `customer_needs` | 顧客ニーズ・需要動向 | 企画部: reference | reference |
> | `action_planning` | 企画部アクション候補 | 企画部: reference | reference |
> | `sales_detail_bg` | 営業担当者・進捗詳細 | 企画部: background | background |
> | `kpi_dashboard` | 商談KPI | 営業改革推進部: primary | primary |
> | `year_plan_ref` | 3ヵ年計画サマリー | 営業改革推進部: reference | reference |
> | `process_check` | 営業プロセス品質チェック | 営業改革推進部: reference | reference |
> | `sales_owner_ref` | 営業担当者情報 | 営業改革推進部: reference | reference |

### 8.3 フィールド定義

#### `role`（文脈的強調）

| 値 | 意味 | 表示上の扱い |
|----|------|------------|
| `primary` | このユーザーにとっての主題 | 最優先表示・強調ボーダー |
| `reference` | 関連参照情報 | 通常表示 |
| `context` | 文脈・背景情報 | 縮小表示・折りたたみ可 |
| `background` | 遠い背景情報 | 最小表示・画面下部 |

#### `component`（コンポーネント型）

| 値 | UIコンポーネント | 表示内容 |
|----|---------------|---------|
| `CardFull` | フルカード | タイトル・詳細・アイテムすべて |
| `CardSummary` | サマリーカード | タイトル・要約・アイテム数 |
| `CardMini` | ミニカード | タイトルのみ・クリックで展開 |
| `ActionList` | アクションリスト | アクションアイテム一覧 |
| `TimelineItem` | タイムライン項目 | 時系列表示 |

#### `granularity`（情報粒度）

| 値 | 表示粒度 |
|----|---------|
| `full` | 全情報を表示 |
| `summary` | 要約のみ表示（アイテム数・代表アイテム） |
| `title_only` | タイトルのみ表示 |
| `hidden` | UX的に非表示（権限による非表示とは別） |

#### `visibility`（表示状態）

| 値 | 意味 | 権限による非表示との違い |
|----|------|----------------------|
| `visible` | 通常表示 | — |
| `collapsed` | 折りたたみ状態（ユーザー操作で展開可） | ユーザーが開ける |
| `hidden` | UX的に非表示 | ユーザーが開けない（ただし権限OKならAPIで取得済み） |

> **重要**：権限による完全非表示（APIレベルで取得しない）は `visibility` フィールドでは制御しない。権限テーブルで別途管理する。

### 8.4 プロファイル継承チェーン

```
default_profile
    ↓ deep merge（role/component/granularity/position をキー単位で上書き）
dept_{部門名}_profile
    ↓ deep merge
dept_{部門名}__role_{役割名}_profile
    ↓ deep merge（差分のみ保存）
user_{userId}_override
    ↓
最終レンダリングプロファイル（resolved profile）
```

#### 継承解決ルール

- 上書き戦略：**deep merge by topicId**（配列要素はtopicIdをキーとして上書き）
- 下位プロファイルが `null` を明示した場合は上位の値を削除（nullによる削除を許容）
- 解決後のプロファイルは必ずバリデーション（JSONスキーマ検証）を通過すること
- 解決結果はRedisに`profile:resolved:{userId}`キーでキャッシュ（TTL 3600秒）

---

## 9. フロントエンド実装仕様

### 9.1 コンポーネントレジストリ

プロファイルの`component`値に対してUIコンポーネントを動的にマッピングする。

```typescript
// componentRegistry.ts

import { CardFull } from './components/CardFull';
import { CardSummary } from './components/CardSummary';
import { CardMini } from './components/CardMini';
import { ActionList } from './components/ActionList';
import { TimelineItem } from './components/TimelineItem';

export const COMPONENT_REGISTRY: Record<string, React.ComponentType<TopicPanelProps>> = {
  CardFull,
  CardSummary,
  CardMini,
  ActionList,
  TimelineItem,
};

// 動的ディスパッチ
export function resolveComponent(componentName: string) {
  const Component = COMPONENT_REGISTRY[componentName];
  if (!Component) {
    console.warn(`Unknown component: ${componentName}. Falling back to CardMini.`);
    return CardMini;
  }
  return Component;
}
```

### 9.2 プロファイルレンダラー

```typescript
// ProfileRenderer.tsx

interface ProfileRendererProps {
  meetingData: MeetingData;
  resolvedProfile: ResolvedProfile;
}

export function ProfileRenderer({ meetingData, resolvedProfile }: ProfileRendererProps) {
  const sortedTopics = [...resolvedProfile.topics]
    .filter(t => t.visibility !== 'hidden')
    .sort((a, b) => a.position.order - b.position.order);

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${resolvedProfile.gridColumns}, 1fr)`,
        gap: '12px',
      }}
    >
      {sortedTopics.map(topicProfile => {
        const topicData = meetingData.topics.find(t => t.topicId === topicProfile.topicId);
        if (!topicData) return null;

        const Component = resolveComponent(topicProfile.component);

        return (
          <div
            key={topicProfile.topicId}
            style={{ gridColumn: `span ${topicProfile.position.span}` }}
          >
            <Component
              data={topicData}
              role={topicProfile.role}
              granularity={topicProfile.granularity}
              visibility={topicProfile.visibility}
            />
          </div>
        );
      })}
    </div>
  );
}
```

### 9.3 TopicPanelProps インターface

```typescript
export interface TopicPanelProps {
  data: TopicData;
  role: 'primary' | 'reference' | 'context' | 'background';
  granularity: 'full' | 'summary' | 'title_only' | 'hidden';
  visibility: 'visible' | 'collapsed' | 'hidden';
  onCustomize?: (topicId: string, changes: Partial<TopicProfileEntry>) => void;
}
```

### 9.4 状態管理方針

- プロファイルデータ：サーバーstateとして管理（React Query / SWR推奨）
- 個人カスタマイズの差分：Zustand等のクライアントstoreで一時保持 → デバウンス後にAPIへ保存
- 再レンダリング最適化：`React.memo` + `topicId` による安定したkey設定

---

## 10. バックエンドAPI仕様

### 10.1 エンドポイント一覧

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/health` | ヘルスチェック |
| `GET` | `/api/meetings` | 会議・訪問記録一覧取得（クエリパラメータでフィルタ） |
| `GET` | `/api/meetings/:meetingId` | 商談会議詳細取得（SFから） |
| `GET` | `/api/visits/:visitId` | 現場訪問詳細取得（SFから） |
| `GET` | `/api/minutes/:meetingId` | 議事録取得（Markdown形式） |
| `GET` | `/api/profiles/resolved` | 解決済みプロファイル取得（継承適用後） |
| `GET` | `/api/profiles/base/:profileId` | ベースプロファイル取得 |
| `PUT` | `/api/profiles/user` | 個人カスタマイズ差分の保存 |
| `DELETE` | `/api/profiles/user` | 個人カスタマイズのリセット |
| `GET` | `/api/profiles/templates` | プロファイルテンプレート一覧 |

### 10.2 `GET /api/meetings/:meetingId` レスポンス例

```json
{
  "meetingId": "OPP-0001",
  "type": "meeting",
  "title": "Q2営業戦略会議",
  "date": "2026-04-16T10:00:00+09:00",
  "topics": [
    {
      "topicId": "competitive_alert",
      "department": "営業",
      "label": "競合の動きに要注意",
      "items": [
        { "id": "i001", "text": "達成見込み: 90%", "type": "metric" },
        { "id": "i002", "text": "競合が積極的アプローチ。価格交渉難航。上長相談要。", "type": "alert" },
        { "id": "i003", "text": "限界利益見込: 未記載", "type": "metric" }
      ]
    },
    {
      "topicId": "timeline_year1",
      "department": "営業",
      "label": "2025年 進行中の打ち手",
      "items": [
        { "id": "t001", "quarter": "Q1", "text": "初回提案", "progress": "done" },
        { "id": "t002", "quarter": "Q2", "text": "価格交渉", "progress": "wip" },
        { "id": "t003", "quarter": "Q3", "text": "全店展開検討", "progress": "pending" },
        { "id": "t004", "quarter": "Q4", "text": "契約締結", "progress": "pending" }
      ]
    }
  ],
  "bant": {
    "b": "年間3,000万円規模",
    "a": "購買部長・現場責任者",
    "n": "新メニュー対応・ノンアル強化",
    "t": "2025年Q3導入希望",
    "c": "競合X社が価格攻勢中",
    "h": "営業部長との関係良好"
  },
  "minutesMarkdown": "## 議事録\n\n### 参加者\n- 営業担当: 田中一郎\n...",
  "sfOpportunityId": "006000000XXXXX",
  "cachedAt": "2026-04-16T10:05:00Z",
  "cacheExpiresAt": "2026-04-16T10:10:00Z"
}
```

### 10.3 `GET /api/profiles/resolved` レスポンス例

```json
{
  "profileId": "dept_営業__role_メンバー__user_override",
  "resolvedFrom": [
    "default_profile",
    "dept_営業_profile",
    "dept_営業__role_メンバー_profile",
    "user_U001_override"
  ],
  "gridColumns": 2,
  "topics": [ ... ],
  "resolvedAt": "2026-04-16T10:05:00Z"
}
```

### 10.4 `PUT /api/profiles/user` リクエスト例（差分のみ）

```json
{
  "changes": [
    {
      "topicId": "timeline_year1",
      "visibility": "visible",
      "granularity": "summary"
    }
  ]
}
```

### 10.5 エラーレスポンス形式

```json
{
  "error": {
    "code": "SF_API_LIMIT_EXCEEDED",
    "message": "Salesforce API daily limit exceeded.",
    "retryAfter": 3600
  }
}
```

---

## 11. データベーススキーマ

### 11.1 テーブル設計（PostgreSQL）

```sql
-- プロファイルマスタ
CREATE TABLE layout_profiles (
  profile_id        VARCHAR(100)  PRIMARY KEY,
  label             VARCHAR(200)  NOT NULL,
  base_profile_id   VARCHAR(100)  REFERENCES layout_profiles(profile_id),
  department        VARCHAR(50),
  role_name         VARCHAR(50),
  profile_json      JSONB         NOT NULL,
  version           INTEGER       NOT NULL DEFAULT 1,
  is_active         BOOLEAN       NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- 個人カスタマイズ差分
CREATE TABLE user_profile_overrides (
  user_id           VARCHAR(100)  NOT NULL,
  meeting_type      VARCHAR(50)   NOT NULL DEFAULT 'default',
  diff_json         JSONB         NOT NULL DEFAULT '[]',
  created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, meeting_type)
);

-- 権限テーブル（表示制御とは独立）
CREATE TABLE topic_permissions (
  user_id           VARCHAR(100)  NOT NULL,
  topic_id          VARCHAR(100)  NOT NULL,
  can_view          BOOLEAN       NOT NULL DEFAULT TRUE,
  can_view_detail   BOOLEAN       NOT NULL DEFAULT TRUE,
  granted_by        VARCHAR(100),
  granted_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, topic_id)
);

-- プロファイルバージョン履歴
CREATE TABLE profile_versions (
  id                BIGSERIAL     PRIMARY KEY,
  profile_id        VARCHAR(100)  NOT NULL,
  version           INTEGER       NOT NULL,
  profile_json      JSONB         NOT NULL,
  changed_by        VARCHAR(100),
  changed_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX idx_layout_profiles_department ON layout_profiles(department);
CREATE INDEX idx_layout_profiles_role ON layout_profiles(role_name);
CREATE INDEX idx_topic_permissions_user ON topic_permissions(user_id);
```

### 11.2 初期データ（シード）

```sql
-- デフォルトプロファイル（全部門共通ベース）
INSERT INTO layout_profiles (profile_id, label, profile_json) VALUES (
  'default_profile',
  'デフォルト（全部門共通）',
  '{
    "gridColumns": 1,
    "topics": [
      {"topicId":"market_insight",    "role":"reference", "component":"CardSummary",  "granularity":"summary",    "position":{"order":1,"span":1},"visibility":"visible"},
      {"topicId":"action_sales",      "role":"reference", "component":"ActionList",   "granularity":"summary",    "position":{"order":2,"span":1},"visibility":"visible"},
      {"topicId":"competitive_alert", "role":"context",   "component":"CardMini",     "granularity":"title_only", "position":{"order":3,"span":1},"visibility":"collapsed"},
      {"topicId":"timeline_year1",    "role":"context",   "component":"CardMini",     "granularity":"title_only", "position":{"order":4,"span":1},"visibility":"collapsed"},
      {"topicId":"year_plan_bg",      "role":"background","component":"CardMini",     "granularity":"title_only", "position":{"order":5,"span":1},"visibility":"collapsed"},
      {"topicId":"bant_info",         "role":"context",   "component":"CardSummary",  "granularity":"summary",    "position":{"order":6,"span":1},"visibility":"collapsed"},
      {"topicId":"kpi_dashboard",     "role":"context",   "component":"CardMini",     "granularity":"title_only", "position":{"order":7,"span":1},"visibility":"collapsed"},
      {"topicId":"process_check",     "role":"context",   "component":"CardMini",     "granularity":"title_only", "position":{"order":8,"span":1},"visibility":"collapsed"}
    ]
  }'
);

-- 営業部門プロファイル（dept_営業_profile）
INSERT INTO layout_profiles (profile_id, label, base_profile_id, department, profile_json) VALUES (
  'dept_営業_profile',
  '営業部門（共通）',
  'default_profile',
  '営業',
  '{
    "gridColumns": 2,
    "topics": [
      {"topicId":"competitive_alert", "role":"primary",    "component":"CardFull",    "granularity":"full",       "position":{"order":1,"span":2},"visibility":"visible"},
      {"topicId":"timeline_year1",    "role":"reference",  "component":"TimelineItem","granularity":"full",       "position":{"order":2,"span":2},"visibility":"visible"},
      {"topicId":"action_sales",      "role":"reference",  "component":"ActionList",  "granularity":"summary",    "position":{"order":3,"span":2},"visibility":"visible"},
      {"topicId":"bant_info",         "role":"reference",  "component":"CardSummary", "granularity":"summary",    "position":{"order":4,"span":1},"visibility":"visible"},
      {"topicId":"year_plan_bg",      "role":"background", "component":"CardMini",    "granularity":"title_only", "position":{"order":5,"span":2},"visibility":"collapsed"}
    ]
  }'
);

-- 企画部プロファイル（dept_企画部_profile）
INSERT INTO layout_profiles (profile_id, label, base_profile_id, department, profile_json) VALUES (
  'dept_企画部_profile',
  '企画部（共通）',
  'default_profile',
  '企画部',
  '{
    "gridColumns": 1,
    "topics": [
      {"topicId":"market_insight",    "role":"primary",    "component":"CardFull",    "granularity":"full",       "position":{"order":1,"span":1},"visibility":"visible"},
      {"topicId":"competitive_env",   "role":"reference",  "component":"CardSummary", "granularity":"summary",    "position":{"order":2,"span":1},"visibility":"visible"},
      {"topicId":"customer_needs",    "role":"reference",  "component":"CardSummary", "granularity":"summary",    "position":{"order":3,"span":1},"visibility":"visible"},
      {"topicId":"action_planning",   "role":"reference",  "component":"ActionList",  "granularity":"summary",    "position":{"order":4,"span":1},"visibility":"visible"},
      {"topicId":"sales_detail_bg",   "role":"background", "component":"CardMini",    "granularity":"title_only", "position":{"order":5,"span":1},"visibility":"collapsed"}
    ]
  }'
);

-- 営業改革推進部プロファイル（dept_改革推進_profile）
INSERT INTO layout_profiles (profile_id, label, base_profile_id, department, profile_json) VALUES (
  'dept_改革推進_profile',
  '営業改革推進部（共通）',
  'default_profile',
  '営業改革推進部',
  '{
    "gridColumns": 2,
    "topics": [
      {"topicId":"kpi_dashboard",     "role":"primary",    "component":"CardFull",    "granularity":"full",       "position":{"order":1,"span":2},"visibility":"visible"},
      {"topicId":"year_plan_ref",     "role":"reference",  "component":"CardFull",    "granularity":"summary",    "position":{"order":2,"span":1},"visibility":"visible"},
      {"topicId":"timeline_year1",    "role":"reference",  "component":"CardSummary", "granularity":"summary",    "position":{"order":3,"span":1},"visibility":"visible"},
      {"topicId":"year_plan_bg",      "role":"background", "component":"CardMini",    "granularity":"title_only", "position":{"order":4,"span":2},"visibility":"collapsed"},
      {"topicId":"process_check",     "role":"reference",  "component":"ActionList",  "granularity":"full",       "position":{"order":5,"span":2},"visibility":"visible"},
      {"topicId":"sales_owner_ref",   "role":"reference",  "component":"CardSummary", "granularity":"summary",    "position":{"order":6,"span":1},"visibility":"visible"}
    ]
  }'
);
```

---

## 12. PoCで検証すべき4つの問い

> これらがPoC固有の検証課題。技術的な可否（JSONの保存等）は既に答えが出ているため対象外。

### 問い①：意味的プロファイルスキーマの表現力

**検証内容**：「主題」「参照」「要約」「非表示」の4種の文脈的強調を、1つのJSONスキーマで矛盾なく表現できるか。

**検証方法**：
- 3部門 × 3役割 = 9プロファイルを実際に作成し、JSONバリデーションを通過させる
- 同一トピックが異なるプロファイルで異なる`role`/`component`を持つシナリオを網羅

**合格基準**：9プロファイルすべてがJSONスキーマバリデーションを通過し、フロントで意図通りにレンダリングされること

---

### 問い②：コンポーネントレジストリの柔軟性

**検証内容**：同一トピックIDのデータを受け取り、プロファイルの`component`定義に応じて異なるUIコンポーネントに動的レンダリングできるか。

**検証方法**：
- `CardFull` / `CardSummary` / `CardMini` / `ActionList` / `TimelineItem` の5種を実装
- 同一のtopicデータを5種すべてにレンダリングし、表示結果を目視・スナップショット確認
- `TimelineItem` はQ別（q1〜q4）データ構造を受け取り、進捗ステータス（`done / wip / warn / pending`）を色分け表示できること

**合格基準**：コンポーネント切り替えに伴いデータ取得APIの呼び出しが発生しないこと（データは1回のみ取得）

---

### 問い③：継承解決の一意性

**検証内容**：デフォルト→部門→役割→個人の4階層を解決したとき、常に一意のプロファイルが定まるか。競合・循環参照・欠損が発生しないか。

**検証方法**：以下の境界値パターンを網羅したユニットテストを作成する

| テストケース | 内容 |
|------------|------|
| デフォルトのみ | 部門・役割プロファイルが存在しない場合 |
| 部門のみ上書き | 役割・個人プロファイルが存在しない場合 |
| 全階層存在 | 4階層すべてが存在し、同一topicIdに異なる設定を持つ場合 |
| 個人がnullで上書き | 個人カスタマイズで上位の設定を明示的に削除する場合 |
| 存在しないtopicId | プロファイルにないtopicIdがデータ側に存在する場合 |
| 循環参照 | `baseProfileId` が循環している場合（検出してエラーを返すこと） |

**合格基準**：全テストケースで解決結果が一意に定まり、循環参照は適切にエラーを返すこと

---

### 問い④：権限とUXの独立性

**検証内容**：「見せない（セキュリティ権限）」と「縮小表示（UX）」が互いに干渉せず独立して機能するか。

**検証方法**：
- `can_view = false` のトピックは、`visibility` の値に関わらずAPIレスポンスに含まれないこと
- `visibility = 'collapsed'` のトピックは、`can_view = true` の場合にユーザー操作で展開できること
- `visibility = 'collapsed'` かつ `can_view = false` の場合、展開できないこと

| パターン | `can_view` | `visibility` | 期待する挙動 |
|---------|-----------|-------------|------------|
| A | true | visible | 通常表示 |
| B | true | collapsed | 折りたたみ表示・展開可 |
| C | true | hidden | UI上は非表示・展開不可 |
| D | false | visible | APIで取得されない・表示されない |
| E | false | collapsed | APIで取得されない・表示されない |
| F | false | hidden | APIで取得されない・表示されない |

**合格基準**：パターンD・E・FでAPIレスポンスにデータが含まれないこと（フロント側でのフィルタに依存しないこと）

---

## 13. テスト戦略

### 13.1 テストレベルと対象

| レベル | 対象 | ツール（案1 Node.js） | ツール（案2 Python） |
|-------|------|-------------------|--------------------|
| ユニット | プロファイル継承解決関数 | Jest | pytest |
| ユニット | JSONスキーマバリデーション | Jest + ajv | pytest + jsonschema |
| ユニット | コンポーネントレジストリ | Jest + React Testing Library | — |
| 結合 | バックエンドAPI（SF疎通含む） | Supertest | pytest + httpx |
| E2E | ユーザー操作シナリオ | Playwright | Playwright |
| スナップショット | コンポーネントレンダリング結果 | Jest Snapshot | — |

### 13.2 自動化必須テスト

以下は必ず自動化してCI/CDに組み込む：

- [ ] プロファイルJSONスキーマバリデーション（全プロファイルファイル）
- [ ] 継承解決関数のユニットテスト（上記6パターン以上）
- [ ] 権限フィルタリングのユニットテスト（上記6パターン）
- [ ] APIエンドポイントの正常系・異常系テスト
- [ ] コンポーネントスナップショットテスト（5コンポーネント × 3グラニュラリティ）

### 13.3 手動確認必須テスト

以下は自動化が困難なため手動確認：

- [ ] 「意味的に正しいか」の目視確認（A部門ユーザーとしてログインし、B部門トピックが縮小表示になっているか）
- [ ] パフォーマンス確認（20トピック表示時の初期レンダリング時間が2秒以内）
- [ ] レイアウト崩壊がないかの目視確認（各ブレークポイント）

---

## 14. 実装フェーズ計画

### Phase 0（並行実施：1〜2日）

- [ ] Salesforce Sandbox環境の準備・管理者権限確認
- [ ] RSA鍵ペアの生成
- [ ] AWS環境のセットアップ（VPC・Subnet・SecurityGroup）

### Phase 1（SF連携基盤：2〜3日）

- [ ] Connected Appの作成・ポリシー設定
- [ ] AWS Secrets Managerへの秘密鍵登録
- [ ] JWT Bearer Flow実装・疎通テスト
- [ ] Opportunity SOQLクエリの動作確認
- [ ] Redis キャッシュの実装

> **合格基準**：SOQLでOpportunityデータが取得でき、Redisにキャッシュされること

### Phase 2（スキーマ・DB：2日）

- [ ] PostgreSQLテーブルの作成（DDL実行）
- [ ] 初期プロファイルデータのシード投入（デフォルト + 3部門 × 3役割 = 10プロファイル）
- [ ] JSONスキーマバリデーション実装
- [ ] 継承解決ロジック実装・ユニットテスト作成

> **合格基準**：問い③のユニットテスト全パターンがパス

### Phase 3（バックエンドAPI：2〜3日）

- [ ] `/api/meetings` 一覧エンドポイントの実装（フィルタ・ページング対応）
- [ ] `/api/meetings/:meetingId` の実装（`bant`・`minutesMarkdown` フィールド含む）
- [ ] `/api/visits/:visitId` の実装（訪問詳細）
- [ ] `/api/minutes/:meetingId` の実装（Markdown形式の議事録取得）
- [ ] `/api/profiles/resolved` の実装（継承解決込み）
- [ ] `/api/profiles/user` PUT/DELETEの実装
- [ ] 権限フィルタリングの実装（機密情報リンクは `can_view: false` で制御）
- [ ] 結合テストの作成・実行

> **合格基準**：問い④のパターンA〜Fすべてで期待通りの挙動

### Phase 4（フロントエンド：4〜5日）

- [ ] コンポーネントレジストリ実装（5コンポーネント）
- [ ] `CardFull` / `CardSummary` / `CardMini` / `ActionList` の4コンポーネント実装
- [ ] `TimelineItem` の実装（Q別打ち手・進捗ドット、`done/wip/warn/pending` 色分け）
- [ ] `ProfileRenderer` の実装
- [ ] 商談詳細画面（`/detail`）の実装（3部門ビュー切り替え）
- [ ] 訪問詳細画面（`/visit`）の実装（3視点ビュー切り替え）
- [ ] 議事録画面（`/minutes`）の実装（Markdown レンダリング）
- [ ] 個人カスタマイズパネル（差分保存・ベース設定参照・リセット）の実装
- [ ] スナップショットテストの作成

> **合格基準**：問い①・②の検証が完了。9プロファイル × 2タイプ（会議/訪問）の全ビューが意図通りにレンダリングされること

### Phase 5（統合・評価：2日）

- [ ] E2Eテスト（Playwright）の実装・実行
- [ ] 3部門 × 3役割の目視確認
- [ ] パフォーマンス計測
- [ ] フィジビリティ評価レポートの作成

---

## 15. 非機能要件

### 15.1 パフォーマンス（PoC目標値）

| 指標 | 目標値 | 計測方法 |
|-----|-------|---------|
| 初期レンダリング時間（SF APIキャッシュヒット時） | < 1秒 | Lighthouse / DevTools |
| 初期レンダリング時間（SF APIキャッシュミス時） | < 3秒 | DevTools |
| プロファイル切り替え時間 | < 200ms | Performance API |
| SF APIコール数/日 | < 500 | SF API Usage Monitor |

### 15.2 セキュリティ

- SF秘密鍵はAWS Secrets Managerにのみ格納。環境変数への直接埋め込み禁止。
- `private_key.pem` はGitリポジトリへのコミント禁止（`.gitignore` 必須）。
- JWT assertion のexpiry は発行から300秒以内に設定。
- 権限フィルタリングはバックエンドAPIレイヤーで実施。フロント側のみのフィルタに依存しない。
- HTTPS通信のみ（HTTP → HTTPSリダイレクト設定）。

### 15.3 PoC期間中のスコープ外

以下はPoC検証スコープ外とし、本番移行フェーズで対応：

- [ ] SF Production orgへの接続
- [ ] マルチテナント対応
- [ ] Salesforce LWC / Apex構成への移植
- [ ] Platform Events / CDC によるリアルタイム同期
- [ ] レイアウトプロファイルの管理UI（管理者向けGUI）
- [ ] ユーザー認証（PoC期間は固定ユーザーIDで代替）

---

## 16. 用語定義

| 用語 | 定義 |
|-----|------|
| **意味的プロファイル** | トピックの位置・サイズではなく、そのユーザーにとっての「役割・コンポーネント型・粒度・文脈強調」を定義したJSON |
| **コンポーネントレジストリ** | コンポーネント名（文字列）からUIコンポーネント（React Component）へのマッピングテーブル。動的ディスパッチを実現する |
| **継承解決（Profile Resolution）** | デフォルト→部門→役割→個人の4階層プロファイルをdeep mergeして、1つの解決済みプロファイルを生成するプロセス |
| **文脈的強調（Contextual Role）** | 「primary / reference / context / background」の4段階。同一トピックが立場によって異なる重み付けで表示されることを制御する |
| **粒度（Granularity）** | 「full / summary / title_only / hidden」の4段階。情報の詳細度を制御する |
| **UX非表示** | `visibility: hidden` によりUIに表示されないが、APIからはデータが返ってくる状態。ユーザー操作で復元可能 |
| **権限非表示** | `can_view: false` によりAPIレスポンスにデータが含まれない状態。フロントエンド側でのフィルタに依存しない |
| **差分保存（Override Only）** | 個人カスタマイズとして、ベースプロファイルからの変更点（差分）のみをDBに保存する方式。ベースプロファイル自体は変更しない |
| **Classic アーキテクチャ** | Grafana・react-grid-layout等の「位置・サイズ・表示順のみをカスタマイズする」従来型ダッシュボード設計 |

---

---

## 17. 議事録生成方式の検討
2026-04-26 12:40

### 17.1 背景と課題

本システムでは会議・訪問記録の議事録を `minutesMarkdown`（Markdown形式）として保存・表示する。
議事録の**生成方式**は大きく2通りに分類される。

- **方式A**: 本システム内に音声認識機能を実装し、会議中にリアルタイムで議事録を自動生成する
- **方式B**: M365 Copilot・Zoom AI Companion 等の外部製品で議事録を生成し、本システムに連携する

どちらを選択するか（または併用するか）は、開発コスト・データ品質・セキュリティ・ユーザー体験に大きく影響する。以下に両方式のメリット・デメリットと実現案を比較する。

---

### 17.2 方式A — 本システム内音声認識実装

#### 処理フロー

```
[会議参加者のマイク]
    │ 音声ストリーム（WebRTC / 録音ファイル）
    ▼
[音声認識エンジン（選択肢）]
    ├── Azure Cognitive Services Speech
    ├── Google Cloud Speech-to-Text
    └── OpenAI Whisper（自社ホスティング）
    │ テキスト変換
    ▼
[議事録構造化処理]
    ├── 話者分離（Speaker Diarization）
    ├── Salesforce 参加者情報との話者マッピング
    └── Markdown 形式への変換・サマリー生成
    ▼
[NeoCRM / Salesforce に書き込み（minutesMarkdown）]
```

#### メリット

| # | メリット | 説明 |
|---|---------|------|
| A1 | **リアルタイム性** | 会議終了直後に議事録が完成。タイムラグがない |
| A2 | **完全なデータ制御** | 音声・テキストが社外に出ないよう制御できる |
| A3 | **深い Salesforce 統合** | 参加者リスト（Opportunity のContacts）と話者を自動マッピングできる |
| A4 | **カスタマイズ性** | 業界固有の用語辞書・商談フェーズ検出・アクション抽出ロジックを独自実装できる |
| A5 | **長期コスト** | Whisper 等を自社ホスティングすればユーザー数に比例した従量費用が発生しない |

#### デメリット

| # | デメリット | 説明 |
|---|----------|------|
| A-D1 | **開発コストが高い** | STT・話者分離・NLP・変換パイプラインの構築に 3〜6 ヶ月以上を要する |
| A-D2 | **日本語認識精度の課題** | 業界用語・固有名詞（製品名・人名）の誤認識が多く、後編集コストが発生する |
| A-D3 | **インフラ複雑化** | 音声ストリーミング・大容量ストレージ・GPU 処理基盤が追加で必要になる |
| A-D4 | **会議システム依存** | Teams・Webex・Zoom それぞれで音声取得 API が異なり、対応コストが複数発生する |
| A-D5 | **PoC 範囲超過** | 本 PoC の検証スコープ（プロファイル解決・コンポーネントレンダリング）から大きく外れる |

---

### 17.3 方式B — 外部製品連携（M365 Copilot 等）

#### 処理フロー

```
[Teams / Zoom / Meet での会議]
    │ 外部製品が自動録音・文字起こし・要約を実行
    ▼
[外部製品が議事録を生成]
    ├── M365 Copilot（Microsoft Teams）
    ├── Zoom AI Companion
    └── Google Gemini in Meet
    │ Webhook / Graph API / メール転送
    ▼
[NeoCRM Minutes Connector]
    ├── 受信した議事録テキストを minutesMarkdown 形式に変換
    ├── Salesforce 商談 ID（OPP-XXXX）と紐付け
    └── PUT /api/minutes/:meetingId で書き込み
    ▼
[NeoCRM / Salesforce に保存]
```

#### メリット

| # | メリット | 説明 |
|---|---------|------|
| B1 | **開発コストが低い** | 音声認識は外部製品が担う。コネクター実装（1〜2 週間）のみで済む |
| B2 | **高品質な日本語認識** | M365 Copilot 等は Microsoft が継続改善しており、業界用語の精度も高い |
| B3 | **ユーザー学習コストゼロ** | すでに Teams を利用している組織ではツール追加が不要 |
| B4 | **複数ツール対応の拡張性** | アダプターパターンで設計すれば、製品変更時もコネクター差し替えだけで対応できる |
| B5 | **PoC 適合性が高い** | 議事録生成を外部委任し、PoC 検証スコープ（プロファイル解決）に集中できる |

#### デメリット

| # | デメリット | 説明 |
|---|----------|------|
| B-D1 | **外部依存リスク** | M365 Copilot の価格改定・API 仕様変更・サービス終了の影響を受ける |
| B-D2 | **データプライバシー** | 会議音声・議事録が外部クラウドに保存されるため、機密情報漏洩リスクがある |
| B-D3 | **リアルタイム性の低下** | Copilot の処理タイムラグにより、会議終了後数分〜十数分で議事録が届く |
| B-D4 | **出力フォーマットの不統一** | 各製品の出力形式が異なり、`minutesMarkdown` 形式への変換コストが製品ごとに発生する |
| B-D5 | **ライセンスコスト** | M365 Copilot は +$30/ユーザー/月のライセンスが必要（未契約組織は追加費用） |

---

### 17.4 方式比較

| 評価軸 | 方式A（自社実装） | 方式B（外部連携） | PoC 推奨 |
|--------|----------------|----------------|---------|
| 開発コスト | ✗ 高（3〜6 ヶ月以上） | ✅ 低（1〜2 週間） | **方式B** |
| 日本語認識精度 | △ 調整次第 | ✅ 高（M365 Copilot） | **方式B** |
| リアルタイム性 | ✅ 即時 | △ 数分のタイムラグ | 方式A |
| データ制御・機密性 | ✅ 完全制御 | ✗ 外部クラウド依存 | 方式A |
| カスタマイズ性 | ✅ 高 | ✗ 製品仕様に依存 | 方式A |
| PoC スコープ適合 | ✗ 範囲外 | ✅ 高 | **方式B** |
| ランニングコスト | △ インフラ費用 | ✗ ライセンス +$30/人 | 方式A |
| 保守コスト | ✗ 高 | ✅ 低 | **方式B** |
| セキュリティ | ✅ 高 | △ 規約・設定次第 | 方式A |
| PoC 期間内の実現可能性 | ✗ 困難 | ✅ 可能 | **方式B** |

> **判定**: PoC フェーズでは **方式B** を採用。本番フェーズでは **方式A + B の併用設計（コネクターパターン）** に移行する。

---

### 17.5 推奨実現案

#### PoC フェーズ: 方式B（外部連携コネクターのみ実装）

議事録生成エンジン自体は PoC のスコープ外とし、**M365 Copilot → NeoCRM への連携コネクター**のみを実装して動作を検証する。

```
PoC 実装スコープ:
  ✅ Webhook 受信エンドポイント（POST /api/webhooks/minutes）
  ✅ M365 Copilot 出力 → minutesMarkdown 変換ロジック
  ✅ Salesforce 商談 ID（OPP-XXXX）との自動紐付け
  ✅ minutes.html での Markdown レンダリング表示
  ✗ 音声認識エンジン（PoC 外・本番フェーズで検討）
```

#### 本番フェーズ: 方式A + B の併用（コネクターパターン）

本番移行後は複数の議事録ソースを**統一インターフェース**で受け入れる設計に移行する。

```
[音声認識エンジン（方式A）]  [M365 Copilot（方式B）]  [手動入力]
          │                        │                    │
          ▼                        ▼                    ▼
 ┌──────────────────────────────────────────────────────┐
 │       Minutes Connector（統一変換レイヤー）             │
 │  interface MinutesSource {                           │
 │    sourceType: 'whisper' | 'm365' | 'zoom' | 'manual'│
 │    rawContent: string                                │
 │    opportunityId: string                             │
 │    participants: string[]                            │
 │  }                                                   │
 │  → toMarkdown(): string  （共通変換メソッド）           │
 └──────────────────────────┬───────────────────────────┘
                            │
                            ▼
              [NeoCRM / Salesforce に保存（minutesMarkdown）]
```

**コネクター設計のポイント**:
- `MinutesSource` インターフェースで入力源を抽象化し、各ソース用のアダプター（`M365CopilotAdapter`, `WhisperAdapter`, `ManualInputAdapter`）を個別実装する
- 変換後の `minutesMarkdown` フォーマットを統一することで、議事録画面（`minutes.html`）への変更を不要にする
- アダプターの差し替えは設定変更のみで対応できるよう、DI（依存性注入）パターンで設計する

---

### 17.6 WhisperX の採用検討

#### 概要

[WhisperX](https://github.com/m-bain/whisperX) は OpenAI Whisper をベースに高速化・話者分離・単語タイムスタンプを追加した OSS の音声認識エンジンである。
方式A（本システム内音声認識）の実装エンジン候補として評価する。

| 指標 | 内容 |
|------|------|
| GitHub スター数 | 21,500 以上（2026年4月時点） |
| 最新バージョン | v3.8.5（2026年4月リリース） |
| ライセンス | BSD-2-Clause（**商用利用可**） |
| メンテナンス | アクティブ（継続的リリース） |
| GPU 要件 | CUDA 12.8 推奨 / 8GB 未満の GPU メモリで動作可 |

#### 標準 Whisper との主な差分

| 機能 | 標準 Whisper | WhisperX |
|------|-------------|---------|
| 処理速度 | ベースライン | **最大 70 倍高速**（バッチ推論 + faster-whisper バックエンド） |
| タイムスタンプ精度 | 発話セグメント単位 | **単語レベル**（wav2vec2 アライメント） |
| 話者分離 | なし | **あり**（各発言に Speaker ID を自動付与） |
| VAD 前処理 | なし | あり（ハルシネーション削減） |
| GPU メモリ効率 | — | バッチサイズ調整で 8GB 未満に収まる |

#### 本システムへの適合性評価

##### メリット

| # | 内容 | NeoCRM への効果 |
|---|------|--------------|
| W1 | **話者分離が標準装備** | 「誰が何を言ったか」を自動識別。Salesforce の参加者リストと話者 ID をマッピングし、より精度の高い議事録を生成できる |
| W2 | **単語レベルタイムスタンプ** | 会議タイムラインと議事録を時刻で紐付けできる。将来的な「発言ハイライト」機能の基盤になる |
| W3 | **BSD-2-Clause ライセンス** | 商用利用・組み込みが無制限。ライセンス費用が発生しない |
| W4 | **方式A のデメリット緩和** | 処理速度（A-D1 開発コスト削減）・精度（A-D2 改善）・自社ホスティング（A-D2 セキュリティ維持）の3点を同時に解決できる可能性がある |
| W5 | **アクティブ開発** | 2026年4月にも v3.8.5 がリリースされており、継続的な改善が見込める |

##### デメリット・懸念事項

| # | 内容 | 深刻度 | 対応方針 |
|---|------|-------|---------|
| W-D1 | **日本語 wav2vec2 アライメントが非公式** | 🔴 高 | 公式サポート言語は英語・仏語等のみ。日本語の単語タイムスタンプは `wav2vec2-large-xlsr-53-japanese` 等のコミュニティモデルに頼る必要がある。精度は要検証 |
| W-D2 | **GPU インフラが必須** | 🟡 中 | AWS EC2（g4dn.xlarge / T4 GPU）または ECS Fargate + GPU が必要。方式A の A-D3（インフラ複雑化）は依然として解決されない |
| W-D3 | **話者分離の精度限界** | 🟡 中 | 重複発話・騒音環境での精度低下が公式に記載。会議室環境では許容範囲内の可能性もあるが、PoC で実測が必要 |
| W-D4 | **HuggingFace トークン要求** | 🟢 低 | 話者分離（pyannote.audio）を使用する場合、HuggingFace のアクセストークンと pyannote の利用規約同意が必要 |

#### 日本語対応の詳細

WhisperX の日本語対応は2層に分かれており、層ごとに状況が異なる。

```
Layer 1: 文字起こし（Transcription）
  → 標準 Whisper の多言語モデル（large-v3）を使用
  → 日本語は Whisper の学習データに含まれており【対応済み・精度高】

Layer 2: 単語アライメント（Word Timestamps）
  → wav2vec2 言語固有モデルが必要
  → 公式サポートは英語・欧州語のみ
  → 日本語はコミュニティモデル（例: jonatasgrosman/wav2vec2-large-xlsr-53-japanese）
    を手動指定することで動作可能【非公式・精度要検証】
```

> **結論**: 日本語の文字起こし自体は高品質で動作する。単語タイムスタンプは追加作業が必要だが、NeoCRM の議事録表示用途（Markdown テキスト生成）では単語タイムスタンプは必須ではないため、**Layer 1 のみで十分な場合が多い**。

#### 採用推奨度と位置付け

```
PoC フェーズ:  ✗ 採用しない
               → 方式B（M365 Copilot 連携）を優先。
                 WhisperX の日本語精度検証・GPU 環境構築は PoC スコープ外。

本番フェーズ:  ✅ 方式A の第一候補として採用を推奨
               → faster-whisper large-v3（日本語モデル）+ 話者分離 で構成。
                 単語タイムスタンプは日本語モデルの検証結果次第でオプション扱い。
```

#### 本番フェーズの構成案（WhisperX 採用時）

```python
# whisperx_adapter.py（MinutesConnector のアダプター実装例）

import whisperx

def transcribe(audio_path: str, hf_token: str) -> str:
    # Layer 1: 日本語文字起こし
    model = whisperx.load_model("large-v3", device="cuda", language="ja")
    result = model.transcribe(audio_path, batch_size=16)

    # Layer 2: 話者分離（オプション）
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device="cuda")
    diarize_segments = diarize_model(audio_path)
    result = whisperx.assign_word_speakers(diarize_segments, result)

    # Markdown 形式に変換（MinutesSource インターフェース準拠）
    return to_minutes_markdown(result["segments"])
```

---

### 17.7 whisper.cpp の採用検討

#### 概要

[whisper.cpp](https://github.com/ggml-org/whisper.cpp) は OpenAI Whisper モデルを **C/C++ に移植した高性能推論エンジン**である。
Python 依存ゼロ・GPU 不要で動作し、Python バインディングも提供している。

| 指標 | 内容 |
|------|------|
| GitHub スター数 | **49,000 以上**（2026年4月時点。WhisperX の約2.3倍） |
| 最新バージョン | v1.8.1（アクティブ開発中） |
| ライセンス | MIT（**商用利用可・最も制約が少ない**） |
| メンテナンス | ggml-org がアクティブに管理 |
| **GPU 要件** | **不要（CPU のみで動作可）** |
| Python バインディング | あり（FastAPI との統合が可能） |

#### 主な機能・特徴

| 機能 | 内容 |
|------|------|
| リアルタイム音声認識 | あり（約 500ms 間隔でストリーミング処理） |
| 話者分離 | 実験的対応（`-tdrz` オプション / tinydiarize） |
| 量子化サポート | あり（メモリ使用量を大幅削減可能） |
| プラットフォーム対応 | macOS / Linux / Windows / iOS / Android / Raspberry Pi / WebAssembly |
| GPU アクセラレーション | オプション（CUDA / Metal / Vulkan / OpenVINO） |
| バインディング | Python / Node.js / Go / Rust / Ruby / Java / .NET / Swift 等 |

#### 本システムへの適合性評価

##### メリット

| # | メリット | NeoCRM への効果 |
|---|---------|--------------|
| C1 | **GPU 不要・CPU のみで動作** | WhisperX の最大の懸念（A-D3: インフラ複雑化）を根本解消。既存 ECS Fargate に追加デプロイ可能。GPU インスタンス（g4dn.xlarge 等）が不要になりコストが大幅削減 |
| C2 | **MIT ライセンス** | 商用利用・組み込み・改変のすべてが無制限。BSD-2-Clause（WhisperX）よりさらに制約が少ない |
| C3 | **スター数 49k** | WhisperX（21.5k）の約 2.3 倍。世界中の本番環境で実績があり、信頼性が高い |
| C4 | **Python バインディングあり** | `backend/`（FastAPI）から直接呼び出せる。言語の壁がない |
| C5 | **リアルタイム対応** | 500ms 間隔のストリーミング処理により、会議中のライブ文字起こしにも対応できる（将来拡張） |
| C6 | **量子化でさらに軽量化** | モデルを INT8 量子化すれば、メモリ消費をさらに削減できる |

##### デメリット・懸念事項

| # | デメリット | 深刻度 | 対応方針 |
|---|----------|-------|---------|
| C-D1 | **話者分離が実験的（tinydiarize）** | 🟡 中 | 基本的な `[SPEAKER_TURN]` マーカーは取得可能。精度を上げる場合は pyannote.audio を別途組み合わせる（whisper.cpp で文字起こし → pyannote.audio で話者 ID 付与の2段構成） |
| C-D2 | **単語レベルタイムスタンプが非標準** | 🟢 低 | NeoCRM の議事録表示（Markdown テキスト）には単語タイムスタンプは必須でないため影響が少ない |
| C-D3 | **C/C++ ネイティブのため Python との連携はバインディング経由** | 🟢 低 | Python バインディング（`whisper-cpp-python` 等）が充実しており、実用上の問題は少ない |
| C-D4 | **CPU のみの場合、long-form 音声の処理速度** | 🟡 中 | 60分以上の長い会議ではリアルタイム比が 1 倍を下回る可能性がある。量子化・並列処理で緩和可能 |

---

### 17.8 WhisperX vs whisper.cpp — エンジン比較

| 評価軸 | WhisperX | whisper.cpp | NeoCRM 推奨 |
|--------|---------|------------|------------|
| **GPU 要件** | ✗ CUDA 必須（g4dn.xlarge 等） | ✅ **CPU のみで動作可** | **whisper.cpp** |
| **インフラ変更** | ✗ GPU インスタンス追加が必要 | ✅ **既存 Fargate に追加デプロイ可** | **whisper.cpp** |
| **話者分離精度** | ✅ pyannote.audio（成熟） | 🟡 tinydiarize（実験的） | WhisperX |
| **単語タイムスタンプ** | ✅ wav2vec2 アライメント | 🟡 非標準 | WhisperX |
| **日本語文字起こし** | ✅ large-v3 対応 | ✅ large-v3 対応 | 同等 |
| **日本語アライメント** | 🟡 非公式コミュニティモデル | 🟡 （同じく非公式） | 同等 |
| **MIT/商用利用** | 🟡 BSD-2-Clause（可） | ✅ **MIT（最も自由）** | **whisper.cpp** |
| **スター数** | 21.5k | ✅ **49k** | **whisper.cpp** |
| **Python バインディング** | ✅ ネイティブ Python | ✅ バインディングあり | 同等 |
| **リアルタイム対応** | △ バッチ処理主体 | ✅ **ストリーミング対応** | **whisper.cpp** |
| **PoC スコープ適合** | ✗ GPU 環境整備が必要 | 🟡 **Fargate 展開可で比較的容易** | **whisper.cpp** |

> **総合判定**: NeoCRM の本番フェーズの方式A エンジンとして **whisper.cpp を第一候補に変更する**。
> インフラコストと複雑性を大幅に削減でき、既存 AWS 構成（ECS Fargate）に乗せられる点が決定的な優位性。
> 話者分離精度が要件になる場合は whisper.cpp（文字起こし） + pyannote.audio（話者 ID 付与）の2段構成を採用する。

---

### 17.9 推奨エンジン構成（方式A 本番フェーズ）

WhisperX から whisper.cpp への変更を受け、§17.5 の本番構成案を以下に改訂する。

```
[会議録音ファイル（WAV/MP4）]
    │
    ▼
[whisper.cpp（文字起こし）]
    ├── モデル: large-v3（日本語多言語モデル）
    ├── 量子化: Q5_K_M（精度とメモリのバランス）
    └── デプロイ: ECS Fargate（CPU のみ。GPU 不要）
    │ テキスト + セグメントタイムスタンプ
    ▼
[pyannote.audio（話者分離・オプション）]
    ├── 各セグメントに Speaker_00 / Speaker_01 を付与
    └── Salesforce 参加者リストと手動 or 自動マッピング
    │
    ▼
[Minutes Connector（Markdown 変換）]
    └── WhisperCppAdapter.toMarkdown() → minutesMarkdown
    ▼
[NeoCRM / Salesforce に保存]
```

```python
# whisper_cpp_adapter.py（MinutesConnector アダプター実装例）
import subprocess, json

def transcribe_ja(audio_path: str, model: str = "large-v3-q5_k_m") -> str:
    """
    whisper.cpp を subprocess 経由で呼び出し、日本語議事録を Markdown で返す。
    GPU 不要。ECS Fargate（vCPU 2 / 4GB RAM）で動作可。
    """
    result = subprocess.run(
        ["whisper", "-m", f"models/ggml-{model}.bin",
         "-l", "ja", "-f", audio_path, "--output-json"],
        capture_output=True, text=True
    )
    segments = json.loads(result.stdout)["transcription"]
    return _to_minutes_markdown(segments)

def _to_minutes_markdown(segments: list) -> str:
    lines = ["## 議事録\n"]
    for seg in segments:
        speaker = seg.get("speaker", "話者不明")
        text    = seg["text"].strip()
        ts      = seg["timestamps"]["from"]
        lines.append(f"**{speaker}** `{ts}`  \n{text}\n")
    return "\n".join(lines)
```

---

### 17.10 PoC 追加検証ポイント（問い⑨・⑩）

Section 12 の問い①〜④に加え、本方式検討を踏まえて以下を追加検証する。

| 問い | 検証内容 | 合格基準 |
|------|---------|---------|
| 問い⑨ | Webhook 経由で M365 Copilot 形式の議事録テキストを受信し、`minutesMarkdown` に変換して `minutes.html` に表示できるか | 表示が意図通りになること（Markdown の見出し・箇条書きが正常レンダリングされること） |
| 問い⑩ | コネクターのアダプターを差し替えても（方式A → 方式B、方式B → 手動入力）、`minutes.html` の表示に変更が不要であることを確認できるか | アダプター差し替え後も同一画面で正常表示されること |

---

*本文書バージョン：1.1*
*作成日：2026-04-16*
*更新日：2026-04-26（UIモック実装フィードバック反映 — 画面構成4画面化・TopicID日本語化・TimelineItemコンポーネント追加・シードデータ3部門対応・議事録生成方式の検討追加・whisper.cpp 採用検討追加・方式A推奨エンジンを WhisperX → whisper.cpp に変更）*
*対象読者：Claude Code・IT設計者・IT開発者・ITテスター*

"""業界別語彙テンプレートと whisper --prompt 用自然文の生成。

設計原則:
  whisper の --prompt はデコーダーの初期コンテキストとして機能する。
  コンマ区切りの単語リストを渡すとデコーダーが「リストの続き」を生成しようとして
  精度が大幅に低下する。語彙は「〜について話している」という自然文の形で渡す。
  実効上限は ~224 トークン（日本語換算 ~200 文字）。
"""

_VOCAB_TEMPLATES: dict[str, str] = {
    "logistics": (
        "入荷、出荷、ピッキング、仕分け、棚卸し、ロット番号、"
        "フォークリフト、パレット、荷主、発注、受注残、在庫回転率、WMS"
    ),
    "retail": (
        "売場、発注点、欠品、棚割り、陳列、回転率、POS、"
        "エンド、フェイス数、バイヤー、MD、プランオグラム"
    ),
    "sales": (
        "成約率、フォローアップ、アポイントメント、見積もり、提案書、"
        "発注、受注、母数、進捗管理、商談、得意先、クロージング、競合"
    ),
}


def build_initial_prompt(
    meeting_type: str = "opp",
    client_name: str = "",
    owner_name: str = "",
    industry: str = "sales",
) -> str:
    """whisper の --prompt 用の自然文を生成する。

    例:
      "すき家 佐藤 淳、商談会議の会話。成約率、フォローアップ、アポイントメントについて話し合っている。"
    """
    vocab = _VOCAB_TEMPLATES.get(industry, _VOCAB_TEMPLATES["sales"])
    meeting_label = "商談会議" if meeting_type == "opp" else "現場訪問"

    proper_nouns = " ".join(filter(None, [client_name, owner_name]))
    if proper_nouns:
        prompt = f"{proper_nouns}、{meeting_label}の会話。{vocab}について話し合っている。"
    else:
        prompt = f"{meeting_label}の会話。{vocab}について話し合っている。"

    return prompt[:200]

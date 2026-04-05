"""ペイン抽出モジュール。Anthropic APIを使って構造化ペイン情報を抽出する。"""

import hashlib
import json
import logging
import re
import time
from pathlib import Path

import anthropic

from src.config import config
from src.models import ExtractedPain, RawQuestion


_EXTRACT_SYSTEM_PROMPT = """あなたはニーズ分析の専門家です。
日本語のQ&A投稿を読み、そこに「具体的なニーズ（困りごと・非効率・摩擦）」があるかを判定し、
あれば詳細を構造化JSONで返してください。

【判定基準 — is_pain の true/false】

以下はすべて is_pain: false にすること:
- 単なる知識質問（調べれば分かること、「〜とは何ですか」型）
- 比較・選択の相談（「AとBどちらがいい」型）
- 感想・雑談・議論（具体的な困りごとがない）
- 愚痴のみで具体的な障壁の記述がない

以下は is_pain: true にすること（ジャンル不問）:
- 具体的な困りごと・非効率・摩擦を抱えている
- 「何かを達成しようとしているが、障壁がある」状態
- 業務・事務作業、趣味、生活、IT環境など領域は問わない
- 重要: workaround（今どう凌いでいるか）と root_cause（なぜ繰り返すか）を特に重視して抽出すること

【フィールド制約 — 必ず守ること】

■ persona_type: 以下の5択から1つ選ぶ（それ以外は禁止）
  freelancer / consultant / small_biz_owner / employee / other

■ job_to_be_done: **10文字以内**の短い作業名で書く。動詞で終わる。
  良い例: 確定申告、請求書作成、契約書レビュー、経費精算、給与計算、
          融資申請、商標出願、見積作成、月次決算、勤怠管理、
          売上集計、在庫管理、顧客対応、採用面接、議事録作成、
          MOD翻訳、PC環境構築、ファイル共有、評価管理、ツール選定
  悪い例: オンライン販売での評価獲得・信頼構築（長すぎる）

■ pain_category: 以下の11択から1つ選ぶ（それ以外は禁止）
  manual_reentry / document_creation / knowledge_lookup /
  tool_fragmentation / compliance_confusion / approval_bottleneck /
  recurring_admin_work / exception_handling / customer_followup /
  handoff_loss / other

■ root_cause: **30文字以内**で、なぜ繰り返すかの構造的原因を書く。
  良い例: 制度が複雑でツールが未対応
  良い例: 手順が属人化し引き継ぎ不足
  良い例: 複数システム間の連携がない
  悪い例: プラットフォーム側のシステム不備で出品者側では制御できない（長すぎる）

■ current_workaround: **30文字以内**で今の回避策を書く。
  良い例: Excelで手動管理、税理士に毎回確認、都度ネット検索
  回避策がない場合: 「対処なし（放置）」と書く

■ recurrence_hint: 以下の5択から1つ選ぶ
  daily / weekly / monthly / one_off / unknown

■ severity / urgency / willingness_to_pay_proxy / builder_fit: 1〜5の整数
  - severity: 1=軽微, 3=作業が止まることがある, 5=深刻・頻繁に損失が発生
  - urgency: 1=後回しでいい, 3=今週中に解決したい, 5=今すぐ解決したい
  - willingness_to_pay_proxy: 1=無料以外使わない, 3=月額1,000〜5,000円なら, 5=月額1万円以上
  - builder_fit: 1=専門知識が必要, 3=汎用スキルで可能, 5=Python/LLM/APIで十分

出力は必ずJSON配列で返す。各要素のスキーマ:

[
  {
    "question_id": "<question_id>",
    "is_pain": true or false,
    "pain_summary": "ニーズの要約（1〜2文）",
    "persona_type": "上記5択",
    "persona_detail": "例: 建設業の二代目経営者",
    "job_to_be_done": "10文字以内の作業名",
    "pain_stage": "例: 月末処理時、申請準備中",
    "pain_category": "上記11択",
    "current_workaround": "30文字以内",
    "root_cause": "30文字以内",
    "severity": 1〜5,
    "urgency": 1〜5,
    "recurrence_hint": "上記5択",
    "willingness_to_pay_proxy": 1〜5,
    "builder_fit": 1〜5,
    "evidence_text": "根拠となる本文の抜粋（50〜150文字）"
  }
]

is_pain=false の場合、pain_summary以外は空文字列・0でよい。
"""

_VALID_PERSONA = {"freelancer", "consultant", "small_biz_owner", "employee", "other"}
_VALID_CATEGORY = {
    "manual_reentry", "document_creation", "knowledge_lookup",
    "tool_fragmentation", "compliance_confusion", "approval_bottleneck",
    "recurring_admin_work", "exception_handling", "customer_followup",
    "handoff_loss", "other",
}
_VALID_RECURRENCE = {"daily", "weekly", "monthly", "one_off", "unknown"}


def _make_question_id(url: str) -> str:
    """URLからquestion_idを生成する。"""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _parse_extracted_pains(response_text: str, question_ids: list[str]) -> list[ExtractedPain]:
    """LLMレスポンスのJSONをパースしてExtractedPainリストに変換する。

    JSONパース失敗時はis_pain=Falseのフォールバックを返す。
    """
    logger = logging.getLogger(__name__)
    try:
        # コードブロックを除去
        text = response_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("レスポンスがJSON配列でない")

        results: list[ExtractedPain] = []
        for item in parsed:
            try:
                persona = str(item.get("persona_type", "other"))
                if persona not in _VALID_PERSONA:
                    persona = "other"

                category = str(item.get("pain_category", "other"))
                if category not in _VALID_CATEGORY:
                    category = "other"

                recurrence = str(item.get("recurrence_hint", "unknown"))
                if recurrence not in _VALID_RECURRENCE:
                    recurrence = "unknown"

                job = str(item.get("job_to_be_done", ""))
                if len(job) > 15:
                    logger.debug("job_to_be_done切り詰め: %s → %s", job, job[:10])
                    job = job[:10]

                root_cause = str(item.get("root_cause", ""))
                if len(root_cause) > 40:
                    root_cause = root_cause[:30]

                workaround = str(item.get("current_workaround", ""))
                if len(workaround) > 40:
                    workaround = workaround[:30]

                severity = max(1, min(5, int(item.get("severity", 1))))
                urgency = max(1, min(5, int(item.get("urgency", 1))))
                wtp = max(1, min(5, int(item.get("willingness_to_pay_proxy", 1))))
                builder_fit = max(1, min(5, int(item.get("builder_fit", 1))))

                pain = ExtractedPain(
                    question_id=str(item.get("question_id", "")),
                    is_pain=bool(item.get("is_pain", False)),
                    pain_summary=str(item.get("pain_summary", "")),
                    persona_type=persona,
                    persona_detail=str(item.get("persona_detail", "")),
                    job_to_be_done=job,
                    pain_stage=str(item.get("pain_stage", "")),
                    pain_category=category,
                    current_workaround=workaround,
                    root_cause=root_cause,
                    severity=severity,
                    urgency=urgency,
                    recurrence_hint=recurrence,
                    willingness_to_pay_proxy=wtp,
                    builder_fit=builder_fit,
                    evidence_text=str(item.get("evidence_text", "")),
                )
                results.append(pain)
            except Exception as e:
                logger.warning("ペインアイテムパースエラー: %s  item=%s", e, item)

        return results

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("JSONパース失敗、フォールバック: %s", e)
        # フォールバック: 全件is_pain=False
        return [
            ExtractedPain(
                question_id=qid,
                is_pain=False,
                pain_summary="パース失敗",
                persona_type="other",
                persona_detail="",
                job_to_be_done="",
                pain_stage="",
                pain_category="other",
                current_workaround="",
                root_cause="",
                severity=1,
                urgency=1,
                recurrence_hint="unknown",
                willingness_to_pay_proxy=1,
                builder_fit=1,
                evidence_text="",
            )
            for qid in question_ids
        ]


class Extractor:
    """Anthropic APIを使ってペインを抽出するクラス。"""

    BATCH_SIZE = 5

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def _build_user_message(self, batch: list[RawQuestion]) -> str:
        """バッチの質問からユーザーメッセージを構築する。"""
        parts = []
        for q in batch:
            qid = _make_question_id(q.url)
            body_truncated = q.body[:config.MAX_BODY_LENGTH]
            parts.append(
                f"## question_id: {qid}\n"
                f"カテゴリ: {q.category_major} > {q.category_minor}\n"
                f"タイトル: {q.title}\n"
                f"本文:\n{body_truncated}"
            )
        return "\n\n---\n\n".join(parts)

    def _call_api_with_retry(self, user_message: str) -> str | None:
        """exponential backoffでAPIを最大3回リトライする。"""
        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=config.ANTHROPIC_MODEL,
                    max_tokens=4096,
                    system=_EXTRACT_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                )
                return response.content[0].text
            except anthropic.RateLimitError as e:
                wait = 2 ** attempt * 5
                self.logger.warning("レートリミット (attempt %d): %s  %d秒待機", attempt + 1, e, wait)
                time.sleep(wait)
            except anthropic.APIError as e:
                wait = 2 ** attempt * 3
                self.logger.warning("APIエラー (attempt %d): %s  %d秒待機", attempt + 1, e, wait)
                time.sleep(wait)
        self.logger.error("API呼び出し失敗（3回リトライ後）")
        return None

    def run(self, questions: list[RawQuestion], date_str: str, dry_run: bool = False) -> list[ExtractedPain]:
        """バッチ処理でペインを抽出してJSONに保存する。

        Args:
            questions: フィルタ済みRawQuestionリスト
            date_str: 実行日付 (YYYY-MM-DD)
            dry_run: Trueならダミーデータを返す

        Returns:
            ExtractedPainのリスト（is_pain=Trueのみ後段で使用）
        """
        all_pains: list[ExtractedPain] = []

        if dry_run:
            # dry-run用: 全件をis_pain=Trueの固定データで返す
            self.logger.info("dry-run: APIスキップ")
            for q in questions:
                all_pains.append(ExtractedPain(
                    question_id=_make_question_id(q.url),
                    is_pain=True,
                    pain_summary=f"[dry-run] {q.title[:50]}",
                    persona_type="freelancer",
                    persona_detail="個人事業主",
                    job_to_be_done="業務効率化",
                    pain_stage="日常業務",
                    pain_category="recurring_admin_work",
                    current_workaround="Excelで手動管理",
                    root_cause="ツールが業務フローに対応していない",
                    severity=3,
                    urgency=3,
                    recurrence_hint="weekly",
                    willingness_to_pay_proxy=3,
                    builder_fit=4,
                    evidence_text=q.body[:100],
                ))
        else:
            # バッチ処理
            for i in range(0, len(questions), self.BATCH_SIZE):
                batch = questions[i: i + self.BATCH_SIZE]
                self.logger.info("バッチ処理: %d〜%d件目", i + 1, i + len(batch))

                user_msg = self._build_user_message(batch)
                response_text = self._call_api_with_retry(user_msg)

                if response_text is None:
                    # フォールバック
                    qids = [_make_question_id(q.url) for q in batch]
                    all_pains.extend(_parse_extracted_pains("[]", qids))
                    continue

                batch_qids = [_make_question_id(q.url) for q in batch]
                pains = _parse_extracted_pains(response_text, batch_qids)
                all_pains.extend(pains)
                self.logger.info("バッチ完了: %d件ペイン抽出 (is_pain=True: %d件)", len(pains), sum(p.is_pain for p in pains))

        # JSON保存
        out_dir = Path(config.DATA_DIR) / "extracted"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        data = [p.__dict__ for p in all_pains]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        pain_count = sum(p.is_pain for p in all_pains)
        self.logger.info("extracted保存: %s (全%d件, is_pain=True: %d件)", out_path, len(all_pains), pain_count)
        return all_pains

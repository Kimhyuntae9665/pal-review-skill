"""Summarize saved PAL evidence locally, without network or inference calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def token_counts(records):
    known = dict.fromkeys(TOKEN_FIELDS, 0)
    missing = dict.fromkeys(TOKEN_FIELDS, 0)
    for record in records:
        attempts = record.get("inference_attempts", 0)
        if not attempts:
            continue
        usage = (record.get("actual_identity") or {}).get("usage") or {}
        for field in TOKEN_FIELDS:
            value = usage.get(field)
            if type(value) is int and value >= 0:
                known[field] += value
            else:
                missing[field] += attempts
    return {"known": known, "missing_attempts": missing,
            "complete": not any(missing.values())}


def summarize(result):
    if "reviews" in result:
        records = result["reviews"]
    else:
        requested = result.get("requested") or {}
        records = [{"round": "followup" if result.get("followup_depth") else "independent",
                    "model": requested.get("model"), "provider": requested.get("provider"),
                    "status": result.get("status"), "reason": result.get("reason"),
                    "inference_attempts": result.get("inference_attempts", 0),
                    "actual_identity": result.get("pal_metadata") or {}}]
    groups = {}
    for record in records:
        key = (record.get("provider"), record.get("model"))
        groups.setdefault(key, []).append(record)
    models = []
    for (provider, model), items in groups.items():
        reported = list(dict.fromkeys((item.get("actual_identity") or {}).get("provider_reported_model")
                                     for item in items))
        models.append({"provider": provider, "requested_model": model,
            "provider_reported_models": [value for value in reported if value],
            "identity_missing_records": sum(not (item.get("actual_identity") or {}).get("provider_reported_model")
                                            for item in items),
            "inference_attempts": sum(item.get("inference_attempts", 0) for item in items),
            "completed_reviews": sum(item.get("status") == "review_received" for item in items),
            "rounds": [{"round": item.get("round"), "status": item.get("status"),
                        "reason": item.get("reason")} for item in items],
            "tokens": token_counts(items),
            "remaining_quota": {"status": "unavailable", "reason": "No account quota observation in this result."}})
    return {"schema_version": 1, "source": "saved_response_metadata",
            "models": models, "tokens": token_counts(records),
            "inference_attempts": sum(row["inference_attempts"] for row in models),
            "completed_reviews": sum(row["completed_reviews"] for row in models),
            "codex_remaining": {"status": "requires_live_usage_tool",
                                "reason": "External API usage does not measure Codex account allowance."}}


def cell(value):
    return str(value if value is not None else "미확인").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def token_text(tokens, field):
    known = tokens["known"][field]
    if not tokens["missing_attempts"][field]:
        return f"{known:,}"
    return f"{known:,}+ (일부 미확인)" if known else "미확인"


def render(summary):
    lines = ["# 검토 모델·사용량", "",
             "| 요청 모델 / 서비스 | 제공사 응답 모델 | 단계별 결과 | 입력 | 출력 | 합계 | 외부 API 잔여 |",
             "| --- | --- | --- | ---: | ---: | ---: | --- |"]
    for model in summary["models"]:
        reported = ", ".join(model["provider_reported_models"]) or "미확인"
        if model["identity_missing_records"] and model["provider_reported_models"]:
            reported += " (일부 미확인)"
        stages = "; ".join(f"{item['round']}: {item['status']}" for item in model["rounds"])
        values = [f"{model['requested_model']} / {model['provider']}", reported, stages,
                  *(token_text(model["tokens"], field) for field in TOKEN_FIELDS), "미확인"]
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    lines.extend(["", f"추론 시도 {summary['inference_attempts']}회 · 정상 검토 {summary['completed_reviews']}회. "
                  f"확인된 사용 합계: {token_text(summary['tokens'], 'total_tokens')} 토큰.", "",
                  "실패 응답도 제공사가 사용량을 반환했다면 합계에 포함합니다. 사용량 누락은 0으로 간주하지 않습니다.",
                  "사용 토큰은 이 요청에서 소비한 양이며 남은 한도가 아닙니다. 모델마다 토큰 계산 방식이 다를 수 있습니다.",
                  "외부 API 잔여: 이 실행 기록에 실제 한도 조회값이 없어 미확인입니다.",
                  "Codex 잔여: 최종 답변 전에 사용량 도구로 별도 조회하고 조회 시점·한도 기간·재설정 시각을 표시합니다. "
                  "도구가 없으면 미확인으로 표시하며 토큰 수로 환산하지 않습니다.",
                  "모델 의견은 조언입니다. Codex의 근거 확인·수정·시험 결과는 별도로 보고합니다."])
    return "\n".join(lines) + "\n"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("result", type=Path, help="Saved result.json or rounds manifest.json")
    args = cli.parse_args()
    print(render(summarize(json.loads(args.result.read_text(encoding="utf-8")))), end="")


if __name__ == "__main__":
    main()

# Full Flask TravelBot (A/B 일정 + 스타일 + Google Maps + 요약)
# ------------------------------------------------
#  기능
# - /plan (POST):
#     · 여행 스타일 기반 일정 생성
#     · A/B 등 여러 버전 일정 생성 (num_plans)
#     · Google Maps 링크 + (선택) Places API로 좌표(lat/lng) 추가
#     · LLM을 이용한 요약/핵심포인트 narrative + summary
# - /health (GET): LLM 사용 여부 확인
# ------------------------------------------------

import os
import json
from datetime import datetime
from typing import List, Dict, Any
from dataclasses import dataclass, asdict

import urllib.parse
import requests

from flask import Flask, request, jsonify
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# (선택) OpenAI 클라이언트 – 키 없으면 스킵
USE_LLM = False
try:
    from openai import OpenAI
    if os.getenv("OPENAI_API_KEY"):
        client = OpenAI()
        USE_LLM = True
except Exception:
    USE_LLM = False

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")  # 있으면 Places API 사용

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ----------------------
# 샘플 POI 데이터 (실서비스는 DB/VectorDB/RAG로 대체)
# ----------------------
POIS = [
    # 오사카
    {"city":"osaka","name":"도톤보리","tags":["야경","먹거리","쇼핑"],"avg_stay":90,"walk_min":10,"price":"$","notes":"글리코상 앞 포토스팟"},
    {"city":"osaka","name":"오사카성 공원","tags":["역사","자연"],"avg_stay":120,"walk_min":20,"price":"$","notes":"벚꽃 시즌 인기"},
    {"city":"osaka","name":"우메다 스카이빌딩 공중정원","tags":["야경","전망"],"avg_stay":80,"walk_min":15,"price":"$$","notes":"전망대 입장료 유"},
    {"city":"osaka","name":"가이유칸 수족관","tags":["가족","실내","동물"],"avg_stay":150,"walk_min":18,"price":"$$$","notes":"아이동반 인기"},
    {"city":"osaka","name":"호젠지 요코초","tags":["레트로","먹거리","사진"],"avg_stay":60,"walk_min":8,"price":"$$","notes":"밤 분위기 좋음"},
    # 서울
    {"city":"seoul","name":"북촌 한옥마을","tags":["전통","사진","산책"],"avg_stay":90,"walk_min":15,"price":"$","notes":"한복체험 연계 가능"},
    {"city":"seoul","name":"DDP","tags":["현대건축","전시","사진"],"avg_stay":70,"walk_min":12,"price":"$","notes":"전시 변동"},
    {"city":"seoul","name":"남산서울타워","tags":["전망","야경"],"avg_stay":80,"walk_min":20,"price":"$$","notes":"케이블카 옵션"},
    {"city":"seoul","name":"광장시장","tags":["먹거리","재래시장"],"avg_stay":60,"walk_min":10,"price":"$","notes":"빈대떡·마약김밥"},
]

CITY_INFO = {
    "osaka": {
        "label": "오사카",
        "description": "간사이 지역의 대표 도시로, 먹거리와 야경, 쇼핑이 모두 유명한 여행 도시입니다. 난바·우메다·도톤보리 등 활기찬 번화가가 많습니다.",
        "image_path": "/static/cities/osaka.png",
    },
    "seoul": {
        "label": "서울",
        "description": "대한민국의 수도로, 전통과 현대가 공존하는 도시입니다. 고궁과 한옥마을, 고층 빌딩과 야경, 다양한 먹거리와 쇼핑을 한 번에 즐길 수 있습니다.",
        "image_path": "/static/cities/seoul.jpg",
    },
}


# 샘플 POI 데이터 아래에 추가
CITY_LABELS = {
    "osaka": "오사카",
    "seoul": "서울",
    # 나중에 "tokyo": "도쿄", "kyoto": "교토" 이런 식으로 계속 추가 가능
}


SLOTS = ["Morning","Lunch","Afternoon","Dinner","Night"]

def get_supported_cities():
    # POIS에 있는 도시 + CITY_INFO 키의 합집합
    codes_from_pois = {p["city"] for p in POIS}
    codes_from_info = set(CITY_INFO.keys())
    codes = sorted(codes_from_pois | codes_from_info)

    cities = []
    for code in codes:
        info = CITY_INFO.get(code, {})
        label = info.get("label", code.title())
        description = info.get("description", "")
        image_path = info.get("image_path", "")
        cities.append({
            "code": code,
            "label": label,
            "description": description,
            "image_path": image_path,  # 상대 경로로 내려줌
        })
    return cities



@app.route("/cities", methods=["GET"])
def cities():
    return jsonify({
        "cities": get_supported_cities()
    })



@dataclass
class UserPref:
    city: str
    days: int
    interests: List[str]
    with_kids: bool = False
    budget: str = "$$"
    max_walk_min: int = 20
    travel_style: str = "mixed"  # relax / foodie / sightseeing / shopping / mixed


# ----------------------
# 간단 추천 로직 (+ 여행 스타일 반영)
# ----------------------

def score_poi(poi: Dict[str, Any], pref: UserPref) -> float:
    """도시/도보제약/관심사/스타일을 종합해서 점수 계산"""
    if poi["city"].lower() != pref.city.lower():
        return -1
    if poi["walk_min"] > pref.max_walk_min:
        return -0.5

    # 관심사 겹침 가점
    overlap = len(set(poi["tags"]) & set([t.strip() for t in pref.interests]))
    score = overlap * 2.0

    # 가족여행 가점
    if pref.with_kids and ("가족" in poi["tags"] or "실내" in poi["tags"]):
        score += 1.5

    # 야간/전망 태그는 기본 가점
    if "야경" in poi["tags"] or "전망" in poi["tags"]:
        score += 0.8

    # 여행 스타일별 가중치
    if pref.travel_style == "relax":
        if "자연" in poi["tags"] or "산책" in poi["tags"] or "카페" in poi["tags"]:
            score += 1.5

    elif pref.travel_style == "foodie":
        if "먹거리" in poi["tags"]:
            score += 2.0

    elif pref.travel_style == "sightseeing":
        if "역사" in poi["tags"] or "전통" in poi["tags"] or "전망" in poi["tags"]:
            score += 1.5

    elif pref.travel_style == "shopping":
        if "쇼핑" in poi["tags"] or "재래시장" in poi["tags"]:
            score += 1.5

    # mixed는 기본 점수로 충분
    return score


def plan_itinerary(pref: UserPref, variant: int = 0) -> Dict[str, Any]:
    """
    POI를 하루씩 쭉 채우는 대신,
    여러 날짜에 골고루 분배하는 버전.

    - ranked: 점수 순으로 정렬된 장소 목록
    - variant: A/B 플랜 차이를 위해 시작 위치를 회전시키는 용도
    """

    ranked = sorted(POIS, key=lambda p: score_poi(p, pref), reverse=True)
    ranked = [p for p in ranked if score_poi(p, pref) > 0]

    if not ranked:
        # 추천할 곳이 아예 없을 때도 Day 1..N은 빈 배열로 리턴
        return {
            "city": pref.city,
            "days": pref.days,
            "itinerary": {f"Day {d}": [] for d in range(1, pref.days + 1)},
        }

    # A/B 플랜용 회전
    if variant > 0 and len(ranked) > 1:
        shift = variant % len(ranked)
        ranked = ranked[shift:] + ranked[:shift]

    # Day별 빈 리스트 먼저 생성
    itinerary: Dict[str, List[Dict[str, Any]]] = {
        f"Day {d}": [] for d in range(1, pref.days + 1)
    }

    # POI를 라운드로빈 방식으로 Day 1,2,3,... 에 분배
    for i, poi in enumerate(ranked):
        day_index = i % pref.days        # 0,1,2 → Day 1,2,3
        day_name = f"Day {day_index + 1}"
        day_plan = itinerary[day_name]

        # 해당 날짜에서 몇 번째 슬롯인지에 따라 기본 슬롯 선택
        slot_idx = len(day_plan) % len(SLOTS)
        slot = SLOTS[slot_idx]

        # 야경/전망 태그가 있으면 가능하면 Night에 배치
        if ("야경" in poi["tags"] or "전망" in poi["tags"]):
            used_slots = {item["slot"] for item in day_plan}
            if "Night" not in used_slots:
                slot = "Night"
            elif "Dinner" not in used_slots:
                slot = "Dinner"

        day_plan.append({
            "slot": slot,
            "name": poi["name"],
            "tags": poi["tags"],
            "eta_min": poi["avg_stay"],
            "walk_min": poi["walk_min"],
            "price": poi["price"],
            "notes": poi.get("notes", "")
        })

    return {
        "city": pref.city,
        "days": pref.days,
        "itinerary": itinerary,
    }


# ----------------------
# Google Maps 정보 부여
# ----------------------

def attach_maps_info_to_plan(plan: Dict[str, Any], pref: UserPref) -> None:
    """
    각 일정 아이템에 Google Maps 검색 링크 + (선택) 좌표(lat/lng) 추가
    - maps_url: 항상 추가
    - GOOGLE_MAPS_API_KEY가 있으면 Places Text Search로 lat/lng도 시도
    """
    for day_name, items in plan["itinerary"].items():
        for item in items:
            query = f"{item['name']} {pref.city}"
            encoded = urllib.parse.quote(query)
            item["maps_url"] = f"https://www.google.com/maps/search/?api=1&query={encoded}"

            if GOOGLE_MAPS_API_KEY:
                try:
                    url = (
                        "https://maps.googleapis.com/maps/api/place/textsearch/json"
                        f"?query={encoded}&key={GOOGLE_MAPS_API_KEY}"
                    )
                    res = requests.get(url, timeout=5)
                    data = res.json()
                    if data.get("results"):
                        loc = data["results"][0]["geometry"]["location"]
                        item["lat"] = loc.get("lat")
                        item["lng"] = loc.get("lng")
                except Exception:
                    # API 실패 시 좌표는 생략
                    item["lat"] = None
                    item["lng"] = None


# ----------------------
# LLM 리라이트 + 요약/하이라이트 생성
# ----------------------

def llm_rewrite(pref: UserPref, plan: Dict[str, Any], with_summary: bool = True) -> Dict[str, Any]:
    """
    LLM을 이용해:
    - narrative: 자연어 설명
    - summary: for_who, highlights[], warnings[]
    를 생성. LLM 사용 불가 시 간단 규칙 기반으로 생성.
    """
    if not USE_LLM:
        # LLM 사용 불가 시 fallback
        narrative = (
            f"{pref.city.title()} {pref.days}일 일정 초안입니다. "
            f"관심사: {', '.join(pref.interests)} / 여행 스타일: {pref.travel_style} / "
            f"도보제약 {pref.max_walk_min}분 / 가족동반: {pref.with_kids}. "
            "도시 내 주요 명소를 Morning~Night 슬롯에 배치했습니다."
        )
        summary = {
            "for_who": "해당 도시를 처음 방문하는 여행자, 간단히 주요 스팟만 둘러보고 싶은 사람에게 적합합니다.",
            "highlights": [
                "관심사와 스타일을 반영해 대표적인 스팟 위주로 구성됨",
                "도보 이동 시간이 너무 길지 않도록 제한을 둠",
                "가족 동반 여부에 따라 실내/가족 친화 스팟을 가점"
            ],
            "warnings": [
                "실제 영업시간, 휴무일, 날씨 등에 따라 일정 조정이 필요합니다.",
                "이동 시간과 교통 수단은 현지 상황에 따라 달라질 수 있습니다."
            ]
        }
        return {"narrative": narrative, "summary": summary}

    system_content = (
        "당신은 현실적인 여행 플래너입니다. 사용자 선호(pref)와 추천 일정(plan)을 보고, "
        "한국어로 간결하고 친절한 설명을 만들어 주세요. "
        "다음 JSON 형식으로만 출력해야 합니다:\n\n"
        "{\n"
        "  \"narrative\": \"자연어 설명\",\n"
        "  \"summary\": {\n"
        "    \"for_who\": \"이 일정이 어떤 사람에게 잘 맞는지 한 줄\",\n"
        "    \"highlights\": [\"하이라이트1\", \"하이라이트2\", \"하이라이트3\"],\n"
        "    \"warnings\": [\"주의사항1\", \"주의사항2\"]\n"
        "  }\n"
        "}\n\n"
        "narrative는 4~8문장 정도로, 전체 일정의 분위기와 특징을 설명하세요."
    )
    user_content = json.dumps(
        {"pref": asdict(pref), "plan": plan},
        ensure_ascii=False
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        response_format={"type": "json_object"},
    )

    try:
        parsed = json.loads(resp.choices[0].message.content)
    except Exception:
        # 혹시 JSON 파싱 실패 시 텍스트 전체를 narrative로 간주
        return {
            "narrative": resp.choices[0].message.content,
            "summary": {}
        }

    return {
        "narrative": parsed.get("narrative", ""),
        "summary": parsed.get("summary", {})
    }


# ----------------------
# API
# ----------------------

@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "llm": USE_LLM, "maps": bool(GOOGLE_MAPS_API_KEY)}


@app.route("/plan", methods=["POST"])
def plan():
    data = request.get_json(force=True)

    pref = UserPref(
        city=data.get("city","osaka"),
        days=int(data.get("days",2)),
        interests=data.get("interests", ["먹거리","야경"]),
        with_kids=bool(data.get("with_kids", False)),
        budget=data.get("budget","$$"),
        max_walk_min=int(data.get("max_walk_min", 20)),
        travel_style=data.get("travel_style", "mixed"),
    )

    num_plans = int(data.get("num_plans", 1))
    if num_plans < 1:
        num_plans = 1
    if num_plans > 3:
        num_plans = 3  # 너무 많이는 제한

    with_summary = bool(data.get("with_summary", True))

    plans_payload = []
    for i in range(num_plans):
        draft = plan_itinerary(pref, variant=i)
        attach_maps_info_to_plan(draft, pref)
        enhanced = llm_rewrite(pref, draft, with_summary=with_summary)

        plans_payload.append({
            "id": chr(65 + i),  # 'A', 'B', ...
            "draft": draft,
            "narrative": enhanced.get("narrative", ""),
            "summary": enhanced.get("summary", {}),
        })

    first = plans_payload[0] if plans_payload else None

    return jsonify({
        "pref": asdict(pref),
        "plans": plans_payload,
        # 기존 프론트와의 호환용 (첫 번째 플랜을 기본값으로 제공)
        "draft": first["draft"] if first else None,
        "narrative": first["narrative"] if first else "",
    })


if __name__ == "__main__":
    # 실행:  python travelbot_mvp_app.py
    app.run(host="0.0.0.0", port=8000, debug=True)
